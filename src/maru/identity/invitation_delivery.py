"""Dedicated worker boundary for encrypted platform invitation delivery."""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from urllib.parse import quote
from uuid import UUID, uuid4

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Min, Q, QuerySet
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.identity.invitation_crypto import (
    EncryptedInvitationPayload,
    InvitationCryptoError,
    InvitationDecryptionKeyUnavailableError,
    InvitationPrivateKeyring,
    decrypt_invitation_payload,
)
from maru.identity.invitation_delivery_payload import (
    decode_invitation_delivery_payload,
    invitation_delivery_aad,
)
from maru.identity.invitation_key_config import worker_invitation_private_keyring
from maru.identity.models import (
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryAttempt,
    PlatformIdentityDeliveryLateOutcome,
)

DELIVERY_LEASE_LIFETIME: Final = timedelta(minutes=5)
MAX_DELIVERY_BATCH: Final = 1_000
MAX_RETRY_DELAY: Final = timedelta(hours=1)
INVITATION_DELIVERY_CONTRACT_VERSION: Final = "page10-invitation-delivery-v1"
MAX_PROVIDER_REFERENCE_LENGTH: Final = 160
SMTP_TRANSIENT_MIN: Final = 400
SMTP_TRANSIENT_MAX: Final = 499
SMTP_PERMANENT_MIN: Final = 500
SMTP_PERMANENT_MAX: Final = 599


class InvitationDeliveryError(RuntimeError):
    """Signal invitation delivery."""

    reason_code = "invitation_delivery_failed"

    def __init__(
        self, message: str = "Invitation delivery could not complete."
    ) -> None:
        """Initialize the InvitationDeliveryError instance.

        Parameters
        ----------
        message : str, default='Invitation delivery could not complete.'
            The disclosure-safe message associated with the outcome.
        """
        super().__init__(message)


class InvitationDeliveryDependencyError(InvitationDeliveryError):
    """Signal invitation delivery dependency."""

    reason_code = "invitation_delivery_dependency_unavailable"


@dataclass(frozen=True, slots=True, repr=False)
class InvitationDeliveryMessage:
    """Describe invitation delivery message.

    Attributes
    ----------
    to_email
        The normalized to email used for delivery or identity matching.
    subject
        The tenant-scoped person or resource governed by the operation.
    body
        The body retained in this immutable projection.
    headers
        The headers mapping to validate or transform.
    """

    to_email: str = field(repr=False)
    subject: str
    body: str = field(repr=False)
    headers: dict[str, str] = field(repr=False)

    def __repr__(self) -> str:
        """Return a diagnostic InvitationDeliveryMessage representation.

        Returns
        -------
        str
            A diagnostic representation of the value.
        """
        return "InvitationDeliveryMessage([redacted])"


DeliveryAdapter = Callable[[InvitationDeliveryMessage], str]


@dataclass(frozen=True, slots=True)
class _ClaimedDelivery:
    delivery_id: UUID
    invitation_id: UUID
    challenge_id: UUID
    invitation_version: int
    email: str
    expires_at: datetime
    attempt_number: int
    lease_token: UUID
    started_at: datetime
    provider_idempotency_key: UUID
    envelope: EncryptedInvitationPayload


@dataclass(frozen=True, slots=True)
class _DeliveryOutcome:
    attempt_outcome: str
    safe_error_code: str = ""
    provider_reference: str = ""
    retry_at: datetime | None = None
    uncertain: bool = False


@dataclass(frozen=True, slots=True)
class InvitationDeliveryBacklogSnapshot:
    """Describe invitation delivery backlog snapshot.

    Attributes
    ----------
    eligible_count
        The bounded number of eligible records.
    oldest_eligible_at
        The timezone-aware timestamp for oldest eligible.
    """

    eligible_count: int
    oldest_eligible_at: datetime | None


def _eligible_delivery_queryset(*, at: datetime) -> QuerySet[PlatformIdentityDelivery]:
    return (
        PlatformIdentityDelivery.objects.filter(
            payload_destroyed_at__isnull=True,
        )
        .exclude(
            reconciliation_state=(PlatformIdentityDelivery.ReconciliationState.REQUIRED)
        )
        .filter(
            Q(
                status__in=(
                    PlatformIdentityDelivery.Status.PENDING,
                    PlatformIdentityDelivery.Status.RETRYING,
                ),
                available_at__lte=at,
            )
            | Q(
                status=PlatformIdentityDelivery.Status.PROCESSING,
                lease_expires_at__lte=at,
            )
        )
    )


def platform_identity_delivery_backlog_snapshot(
    *,
    at: datetime | None = None,
) -> InvitationDeliveryBacklogSnapshot:
    """Return global count/time-only evidence, never recipient values.

    Parameters
    ----------
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    InvitationDeliveryBacklogSnapshot
        The InvitationDeliveryBacklogSnapshot produced by platform identity
        delivery backlog snapshot.
    """
    observed_at = at or timezone.now()
    eligible = _eligible_delivery_queryset(at=observed_at)
    oldest_available = eligible.filter(
        status__in=(
            PlatformIdentityDelivery.Status.PENDING,
            PlatformIdentityDelivery.Status.RETRYING,
        )
    ).aggregate(value=Min("available_at"))["value"]
    oldest_lease = eligible.filter(
        status=PlatformIdentityDelivery.Status.PROCESSING,
    ).aggregate(value=Min("lease_expires_at"))["value"]
    candidates = tuple(
        item for item in (oldest_available, oldest_lease) if item is not None
    )
    return InvitationDeliveryBacklogSnapshot(
        eligible_count=eligible.count(),
        oldest_eligible_at=min(candidates) if candidates else None,
    )


def _lock_control() -> PlatformAccountInventoryControl:
    try:
        return PlatformAccountInventoryControl.objects.select_for_update().get(
            singleton=True
        )
    except PlatformAccountInventoryControl.DoesNotExist as error:
        raise InvitationDeliveryDependencyError from error


def _advance_control(control: PlatformAccountInventoryControl) -> None:
    control.aggregate_version = int(control.aggregate_version) + 1
    control.save(update_fields=("aggregate_version", "updated_at"))


def _audit_delivery(
    *,
    delivery: PlatformIdentityDelivery,
    operation: str,
    reason_code: str,
    changed_fields: tuple[str, ...],
    correlation_id: UUID,
    occurred_at: datetime,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="system",
            principal_id=None,
            principal_context_id=None,
            organization_id=None,
            event_edition_id=None,
            capability_code="identity.deliver_account_invitation",
            operation=operation,
            target_type="identity.platform_identity_delivery",
            target_id=delivery.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="identity_delivery_worker",
            obligations=("audit",),
            changed_fields=changed_fields,
            safe_metadata={"contract_version": INVITATION_DELIVERY_CONTRACT_VERSION},
            retention_class="identity-restricted",
        ),
        occurred_at=occurred_at,
    )


def _as_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, memoryview):
        return value.tobytes()
    raise InvitationDeliveryDependencyError


def _claim_delivery(  # noqa: PLR0911, PLR0912, PLR0915
    *,
    delivery_id: UUID,
    correlation_id: UUID,
    private_keyring: InvitationPrivateKeyring,
) -> _ClaimedDelivery | None:
    now = timezone.now()
    with transaction.atomic():
        control = _lock_control()
        delivery = (
            PlatformIdentityDelivery.objects.select_for_update()
            .select_related("invitation", "challenge", "invitation__account")
            .filter(id=delivery_id)
            .first()
        )
        if delivery is None:
            return None
        invitation = delivery.invitation
        challenge = delivery.challenge
        if delivery.status in (
            PlatformIdentityDelivery.Status.DELIVERED,
            PlatformIdentityDelivery.Status.PERMANENT_FAILED,
            PlatformIdentityDelivery.Status.CANCELLED,
        ):
            return None
        if (
            delivery.reconciliation_state
            == PlatformIdentityDelivery.ReconciliationState.REQUIRED
        ):
            return None
        if (
            delivery.status == PlatformIdentityDelivery.Status.PROCESSING
            and delivery.lease_expires_at is not None
            and delivery.lease_expires_at > now
        ):
            return None
        recovered_stale_lease = (
            delivery.status == PlatformIdentityDelivery.Status.PROCESSING
        )
        if recovered_stale_lease:
            if (
                delivery.claimed_at is None
                or delivery.lease_token is None
                or delivery.attempt_count < 1
            ):
                raise InvitationDeliveryDependencyError
            PlatformIdentityDeliveryAttempt.objects.create(
                delivery=delivery,
                attempt_number=delivery.attempt_count,
                lease_token=delivery.lease_token,
                started_at=delivery.claimed_at,
                finished_at=now,
                outcome=PlatformIdentityDeliveryAttempt.Outcome.LEASE_LOST,
                safe_error_code="delivery_lease_expired",
            )
            delivery.claimed_at = None
            delivery.lease_expires_at = None
            delivery.lease_token = None
            if delivery.cancellation_requested_at is not None:
                delivery.status = PlatformIdentityDelivery.Status.CANCELLED
                delivery.cancelled_at = now
                delivery.next_retry_at = None
                delivery.safe_error_code = delivery.cancellation_code
            else:
                delivery.status = PlatformIdentityDelivery.Status.RETRYING
                delivery.next_retry_at = now
                delivery.available_at = now
                delivery.safe_error_code = "delivery_lease_expired"
            delivery.aggregate_version += 1
            delivery.save(
                update_fields=(
                    "aggregate_version",
                    "status",
                    "claimed_at",
                    "lease_expires_at",
                    "lease_token",
                    "next_retry_at",
                    "available_at",
                    "safe_error_code",
                    "cancelled_at",
                    "updated_at",
                )
            )
            _advance_control(control)
            _audit_delivery(
                delivery=delivery,
                operation="identity.account_invitation.delivery_lease_lost",
                reason_code="delivery_lease_expired",
                changed_fields=("lease", "attempt_evidence"),
                correlation_id=correlation_id,
                occurred_at=now,
            )
            if delivery.status == PlatformIdentityDelivery.Status.CANCELLED:
                return None
        invitation_is_not_deliverable = (
            invitation.status != PlatformAccountInvitation.Status.PENDING
            or invitation.current_challenge_id != challenge.id
            or invitation.expires_at <= now
            or challenge.expires_at <= now
            or challenge.consumed_at is not None
            or challenge.invalidated_at is not None
        )
        payload_is_unavailable = (
            delivery.payload_destroyed_at is not None
            or delivery.encrypted_payload is None
            or delivery.wrapped_data_key is None
            or delivery.payload_nonce is None
        )
        if (
            invitation_is_not_deliverable
            or payload_is_unavailable
            or delivery.available_at > now
            or (delivery.next_retry_at is not None and delivery.next_retry_at > now)
            or delivery.attempt_count >= delivery.max_attempts
        ):
            if recovered_stale_lease and (
                invitation_is_not_deliverable
                or payload_is_unavailable
                or delivery.attempt_count >= delivery.max_attempts
            ):
                delivery.status = PlatformIdentityDelivery.Status.PERMANENT_FAILED
                delivery.safe_error_code = (
                    "delivery_attempts_exhausted"
                    if delivery.attempt_count >= delivery.max_attempts
                    else "invitation_not_deliverable"
                )
                delivery.next_retry_at = None
                if delivery.attempt_count >= delivery.max_attempts:
                    delivery.reconciliation_state = (
                        PlatformIdentityDelivery.ReconciliationState.REQUIRED
                    )
                    delivery.reconciliation_required_at = now
                delivery.aggregate_version += 1
                delivery.save(
                    update_fields=(
                        "aggregate_version",
                        "status",
                        "safe_error_code",
                        "next_retry_at",
                        "reconciliation_state",
                        "reconciliation_required_at",
                        "updated_at",
                    )
                )
                _advance_control(control)
                _audit_delivery(
                    delivery=delivery,
                    operation="identity.account_invitation.delivery_result",
                    reason_code=delivery.safe_error_code,
                    changed_fields=(
                        "status",
                        "lease",
                        "attempt_evidence",
                        "reconciliation_state",
                    ),
                    correlation_id=correlation_id,
                    occurred_at=now,
                )
            return None
        if not private_keyring.contains(delivery.encryption_key_id):
            raise InvitationDeliveryDependencyError
        lease_token = uuid4()
        attempt_number = delivery.attempt_count + 1
        delivery.status = PlatformIdentityDelivery.Status.PROCESSING
        delivery.attempt_count = attempt_number
        delivery.claimed_at = now
        delivery.lease_expires_at = now + DELIVERY_LEASE_LIFETIME
        delivery.lease_token = lease_token
        delivery.last_attempt_at = now
        delivery.next_retry_at = None
        delivery.safe_error_code = ""
        delivery.aggregate_version += 1
        delivery.save(
            update_fields=(
                "aggregate_version",
                "status",
                "attempt_count",
                "claimed_at",
                "lease_expires_at",
                "lease_token",
                "last_attempt_at",
                "next_retry_at",
                "safe_error_code",
                "updated_at",
            )
        )
        _advance_control(control)
        _audit_delivery(
            delivery=delivery,
            operation="identity.account_invitation.delivery_claim",
            reason_code="delivery_claimed",
            changed_fields=("status", "lease", "attempt_count"),
            correlation_id=correlation_id,
            occurred_at=now,
        )
        try:
            envelope = EncryptedInvitationPayload(
                encryption_algorithm=delivery.encryption_algorithm,
                encryption_key_id=delivery.encryption_key_id,
                encrypted_payload=_as_bytes(delivery.encrypted_payload),
                wrapped_data_key=_as_bytes(delivery.wrapped_data_key),
                payload_nonce=_as_bytes(delivery.payload_nonce),
                payload_aad_digest=delivery.payload_aad_digest,
            )
        except InvitationCryptoError as error:
            raise InvitationDeliveryDependencyError from error
        return _ClaimedDelivery(
            delivery_id=delivery.id,
            invitation_id=invitation.id,
            challenge_id=challenge.id,
            invitation_version=int(challenge.invitation_version or 0),
            email=invitation.account.email,
            expires_at=invitation.expires_at,
            attempt_number=attempt_number,
            lease_token=lease_token,
            started_at=now,
            provider_idempotency_key=delivery.provider_idempotency_key,
            envelope=envelope,
        )


def _delivery_link(raw_token: str) -> str:
    base_url = settings.MARU_PUBLIC_BASE_URL.rstrip("/")
    return f"{base_url}/accounts/invitations/accept/#code={quote(raw_token, safe='')}"


def _default_delivery_adapter(message: InvitationDeliveryMessage) -> str:
    email = EmailMessage(
        subject=message.subject,
        body=message.body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[message.to_email],
        headers=message.headers,
    )
    sent = email.send(fail_silently=False)
    if sent != 1:
        raise OSError("Invitation email provider did not accept the message.")
    return message.headers["X-Maru-Idempotency-Key"]


def _message_for_claim(
    claim: _ClaimedDelivery,
    *,
    private_keyring: InvitationPrivateKeyring,
) -> InvitationDeliveryMessage:
    aad = invitation_delivery_aad(
        invitation_id=claim.invitation_id,
        challenge_id=claim.challenge_id,
        invitation_version=claim.invitation_version,
        email=claim.email,
    )
    plaintext = decrypt_invitation_payload(
        envelope=claim.envelope,
        expected_aad=aad,
        private_keyring=private_keyring,
    )
    payload = decode_invitation_delivery_payload(plaintext)
    link = _delivery_link(payload.raw_token)
    return InvitationDeliveryMessage(
        to_email=claim.email,
        subject="Complete your Maru account invitation",
        body=(
            "A Maru platform administrator invited this address to create a "
            "person account. This does not grant access to any convention.\n\n"
            "Open the single-use link, choose your own password, and complete "
            f"the invitation before {claim.expires_at.isoformat()}:\n\n{link}\n\n"
            "If you did not expect this message, you can ignore it."
        ),
        headers={
            "X-Maru-Idempotency-Key": str(claim.provider_idempotency_key),
        },
    )


def _retry_at(*, attempt_number: int, now: datetime) -> datetime:
    delay_seconds = min(
        int(MAX_RETRY_DELAY.total_seconds()),
        60 * (2 ** max(0, attempt_number - 1)),
    )
    return now + timedelta(seconds=delay_seconds)


def _attempt_delivery(  # noqa: PLR0911
    claim: _ClaimedDelivery,
    *,
    private_keyring: InvitationPrivateKeyring,
    adapter: DeliveryAdapter,
) -> _DeliveryOutcome:
    try:
        message = _message_for_claim(claim, private_keyring=private_keyring)
    except InvitationDecryptionKeyUnavailableError:
        return _DeliveryOutcome(
            attempt_outcome=PlatformIdentityDeliveryAttempt.Outcome.TRANSIENT_FAILURE,
            safe_error_code="invitation_encryption_key_unavailable",
            retry_at=_retry_at(
                attempt_number=claim.attempt_number,
                now=timezone.now(),
            ),
        )
    except (InvitationCryptoError, ValueError):
        return _DeliveryOutcome(
            attempt_outcome=PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE,
            safe_error_code="invitation_encrypted_payload_invalid",
        )
    try:
        provider_reference = adapter(message)
    except smtplib.SMTPRecipientsRefused:
        return _DeliveryOutcome(
            attempt_outcome=PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE,
            safe_error_code="email_recipient_rejected",
        )
    except (smtplib.SMTPConnectError, ConnectionRefusedError):
        return _DeliveryOutcome(
            attempt_outcome=PlatformIdentityDeliveryAttempt.Outcome.TRANSIENT_FAILURE,
            safe_error_code="email_provider_unavailable",
            retry_at=_retry_at(
                attempt_number=claim.attempt_number,
                now=timezone.now(),
            ),
        )
    except (
        smtplib.SMTPServerDisconnected,
        TimeoutError,
        ConnectionResetError,
        BrokenPipeError,
    ):
        return _DeliveryOutcome(
            attempt_outcome=PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
            safe_error_code="email_delivery_uncertain",
            retry_at=_retry_at(
                attempt_number=claim.attempt_number,
                now=timezone.now(),
            ),
            uncertain=True,
        )
    except smtplib.SMTPResponseException as error:
        if SMTP_TRANSIENT_MIN <= error.smtp_code <= SMTP_TRANSIENT_MAX:
            return _DeliveryOutcome(
                attempt_outcome=(
                    PlatformIdentityDeliveryAttempt.Outcome.TRANSIENT_FAILURE
                ),
                safe_error_code="email_provider_unavailable",
                retry_at=_retry_at(
                    attempt_number=claim.attempt_number,
                    now=timezone.now(),
                ),
            )
        if SMTP_PERMANENT_MIN <= error.smtp_code <= SMTP_PERMANENT_MAX:
            return _DeliveryOutcome(
                attempt_outcome=(
                    PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE
                ),
                safe_error_code="email_provider_rejected",
            )
        return _DeliveryOutcome(
            attempt_outcome=PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
            safe_error_code="email_delivery_uncertain",
            retry_at=_retry_at(
                attempt_number=claim.attempt_number,
                now=timezone.now(),
            ),
            uncertain=True,
        )
    except smtplib.SMTPException:
        return _DeliveryOutcome(
            attempt_outcome=PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
            safe_error_code="email_delivery_uncertain",
            retry_at=_retry_at(
                attempt_number=claim.attempt_number,
                now=timezone.now(),
            ),
            uncertain=True,
        )
    except OSError:
        return _DeliveryOutcome(
            attempt_outcome=PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
            safe_error_code="email_delivery_uncertain",
            retry_at=_retry_at(
                attempt_number=claim.attempt_number,
                now=timezone.now(),
            ),
            uncertain=True,
        )
    return _provider_result(provider_reference, claim=claim)


def _provider_result(
    provider_reference: object,
    *,
    claim: _ClaimedDelivery,
) -> _DeliveryOutcome:
    if (
        not isinstance(provider_reference, str)
        or not provider_reference
        or len(provider_reference) > MAX_PROVIDER_REFERENCE_LENGTH
        or not provider_reference.isprintable()
    ):
        return _DeliveryOutcome(
            attempt_outcome=PlatformIdentityDeliveryAttempt.Outcome.UNCERTAIN,
            safe_error_code="email_provider_reference_invalid",
            retry_at=_retry_at(
                attempt_number=claim.attempt_number,
                now=timezone.now(),
            ),
            uncertain=True,
        )
    return _DeliveryOutcome(
        attempt_outcome=PlatformIdentityDeliveryAttempt.Outcome.DELIVERED,
        provider_reference=provider_reference,
    )


def _record_late_outcome(
    *,
    delivery: PlatformIdentityDelivery,
    claim: _ClaimedDelivery,
    outcome: _DeliveryOutcome,
    correlation_id: UUID,
    observed_at: datetime,
    control: PlatformAccountInventoryControl,
) -> None:
    settled_attempt = PlatformIdentityDeliveryAttempt.objects.filter(
        delivery=delivery,
        attempt_number=claim.attempt_number,
        lease_token=claim.lease_token,
    ).first()
    if (
        settled_attempt is not None
        and settled_attempt.outcome
        != PlatformIdentityDeliveryAttempt.Outcome.LEASE_LOST
    ):
        return
    if delivery.cancellation_requested_at is not None:
        classification = (
            PlatformIdentityDeliveryLateOutcome.Classification.LIFECYCLE_CANCELLED
        )
    elif settled_attempt is not None:
        classification = (
            PlatformIdentityDeliveryLateOutcome.Classification.LEASE_SUPERSEDED
        )
    else:
        classification = (
            PlatformIdentityDeliveryLateOutcome.Classification.TERMINAL_STATE
        )
    _late_outcome, created = PlatformIdentityDeliveryLateOutcome.objects.get_or_create(
        delivery=delivery,
        attempt_number=claim.attempt_number,
        lease_token=claim.lease_token,
        defaults={
            "observed_at": observed_at,
            "outcome": outcome.attempt_outcome,
            "classification": classification,
            "provider_reference": outcome.provider_reference,
            "safe_error_code": outcome.safe_error_code,
        },
    )
    if not created:
        return
    if (
        outcome.attempt_outcome == PlatformIdentityDeliveryAttempt.Outcome.DELIVERED
        and delivery.cancellation_requested_at is None
    ):
        delivery.reconciliation_state = (
            PlatformIdentityDelivery.ReconciliationState.REQUIRED
        )
        delivery.reconciliation_required_at = observed_at
        delivery.reconciled_at = None
        delivery.reconciliation_code = ""
    delivery.aggregate_version += 1
    delivery.save(
        update_fields=(
            "aggregate_version",
            "reconciliation_state",
            "reconciliation_required_at",
            "reconciled_at",
            "reconciliation_code",
            "updated_at",
        )
    )
    _advance_control(control)
    _audit_delivery(
        delivery=delivery,
        operation="identity.account_invitation.delivery_late_result",
        reason_code=(
            "late_provider_delivery"
            if outcome.attempt_outcome
            == PlatformIdentityDeliveryAttempt.Outcome.DELIVERED
            else "late_provider_result"
        ),
        changed_fields=("late_outcome", "reconciliation_state"),
        correlation_id=correlation_id,
        occurred_at=observed_at,
    )


def _finalize_delivery(  # noqa: PLR0915
    *,
    claim: _ClaimedDelivery,
    outcome: _DeliveryOutcome,
    correlation_id: UUID,
) -> str:
    finished_at = timezone.now()
    with transaction.atomic():
        control = _lock_control()
        delivery = (
            PlatformIdentityDelivery.objects.select_for_update()
            .filter(id=claim.delivery_id)
            .first()
        )
        if (
            delivery is None
            or delivery.status != PlatformIdentityDelivery.Status.PROCESSING
            or delivery.lease_token != claim.lease_token
            or delivery.attempt_count != claim.attempt_number
        ):
            if delivery is not None:
                _record_late_outcome(
                    delivery=delivery,
                    claim=claim,
                    outcome=outcome,
                    correlation_id=correlation_id,
                    observed_at=finished_at,
                    control=control,
                )
            return delivery.status if delivery is not None else "unavailable"
        attempt_outcome = outcome.attempt_outcome
        retry_at = outcome.retry_at
        if (
            attempt_outcome == PlatformIdentityDeliveryAttempt.Outcome.TRANSIENT_FAILURE
            and delivery.attempt_count >= delivery.max_attempts
        ):
            attempt_outcome = PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE
            retry_at = None
            outcome = _DeliveryOutcome(
                attempt_outcome=attempt_outcome,
                safe_error_code="email_delivery_attempts_exhausted",
            )
        PlatformIdentityDeliveryAttempt.objects.create(
            delivery=delivery,
            attempt_number=claim.attempt_number,
            lease_token=claim.lease_token,
            started_at=claim.started_at,
            finished_at=finished_at,
            outcome=attempt_outcome,
            provider_reference=outcome.provider_reference,
            safe_error_code=outcome.safe_error_code,
            next_retry_at=(
                retry_at
                if attempt_outcome
                == PlatformIdentityDeliveryAttempt.Outcome.TRANSIENT_FAILURE
                else None
            ),
        )
        delivery.claimed_at = None
        delivery.lease_expires_at = None
        delivery.lease_token = None
        if delivery.cancellation_requested_at is not None:
            delivery.status = PlatformIdentityDelivery.Status.CANCELLED
            delivery.cancelled_at = finished_at
            delivery.safe_error_code = delivery.cancellation_code
            delivery.next_retry_at = None
            if attempt_outcome == PlatformIdentityDeliveryAttempt.Outcome.DELIVERED:
                delivery.provider_reference = outcome.provider_reference
                reason_code = "delivery_cancelled_after_provider_delivery"
            else:
                reason_code = "delivery_cancelled_after_provider_result"
        elif attempt_outcome == PlatformIdentityDeliveryAttempt.Outcome.DELIVERED:
            delivery.status = PlatformIdentityDelivery.Status.DELIVERED
            delivery.delivered_at = finished_at
            delivery.provider_reference = outcome.provider_reference
            delivery.safe_error_code = ""
            delivery.next_retry_at = None
            delivery.encryption_algorithm = ""
            delivery.encryption_key_id = ""
            delivery.encrypted_payload = None
            delivery.wrapped_data_key = None
            delivery.payload_nonce = None
            delivery.payload_aad_digest = ""
            delivery.payload_destroyed_at = finished_at
            delivery.payload_destruction_reason = (
                PlatformIdentityDelivery.PayloadDestructionReason.DELIVERED
            )
            reason_code = "delivery_confirmed"
        elif (
            attempt_outcome == PlatformIdentityDeliveryAttempt.Outcome.PERMANENT_FAILURE
        ):
            delivery.status = PlatformIdentityDelivery.Status.PERMANENT_FAILED
            delivery.safe_error_code = outcome.safe_error_code
            delivery.next_retry_at = None
            reason_code = outcome.safe_error_code
        else:
            delivery.status = PlatformIdentityDelivery.Status.RETRYING
            delivery.safe_error_code = outcome.safe_error_code
            delivery.next_retry_at = retry_at
            delivery.available_at = retry_at or finished_at
            reason_code = outcome.safe_error_code
            if outcome.uncertain:
                delivery.reconciliation_state = (
                    PlatformIdentityDelivery.ReconciliationState.REQUIRED
                )
                delivery.reconciliation_required_at = finished_at
                delivery.reconciled_at = None
                delivery.reconciliation_code = ""
        delivery.aggregate_version += 1
        delivery.save()
        _advance_control(control)
        _audit_delivery(
            delivery=delivery,
            operation="identity.account_invitation.delivery_result",
            reason_code=reason_code,
            changed_fields=(
                "status",
                "lease",
                "attempt",
                "delivery_evidence",
            ),
            correlation_id=correlation_id,
            occurred_at=finished_at,
        )
        return delivery.status


def deliver_platform_identity_invitation(
    delivery_id: UUID,
    *,
    private_keyring: InvitationPrivateKeyring | None = None,
    adapter: DeliveryAdapter | None = None,
    correlation_id: UUID | None = None,
) -> str:
    """Lease, decrypt, deliver, and record one durable invitation message.

    Parameters
    ----------
    delivery_id : UUID
        The delivery identifier within the requested scope.
    private_keyring : InvitationPrivateKeyring | None, default=None
        The configured private signing keys indexed by key identifier.
    adapter : DeliveryAdapter | None, default=None
        The external-system adapter isolated behind this boundary.
    correlation_id : UUID | None, default=None
        The request correlation identifier used for audit tracing.

    Returns
    -------
    str
        The normalized text for deliver platform identity invitation.

    Raises
    ------
    InvitationDeliveryDependencyError
        If the operation encounters a invitation delivery dependency condition.
    """
    correlation = correlation_id or uuid4()
    try:
        keyring = private_keyring or worker_invitation_private_keyring()
    except InvitationCryptoError as error:
        raise InvitationDeliveryDependencyError from error
    claim = _claim_delivery(
        delivery_id=delivery_id,
        correlation_id=correlation,
        private_keyring=keyring,
    )
    if claim is None:
        current = PlatformIdentityDelivery.objects.filter(id=delivery_id).first()
        return current.status if current is not None else "unavailable"
    outcome = _attempt_delivery(
        claim,
        private_keyring=keyring,
        adapter=adapter or _default_delivery_adapter,
    )
    return _finalize_delivery(
        claim=claim,
        outcome=outcome,
        correlation_id=correlation,
    )


def deliver_pending_platform_identity_invitations(
    *,
    limit: int = 100,
    private_keyring: InvitationPrivateKeyring | None = None,
    adapter: DeliveryAdapter | None = None,
) -> tuple[int, int]:
    """Return deliver pending platform identity invitations.

    Parameters
    ----------
    limit : int, default=100
        The maximum number of records to process.
    private_keyring : InvitationPrivateKeyring | None, default=None
        The configured private signing keys indexed by key identifier.
    adapter : DeliveryAdapter | None, default=None
        The external-system adapter isolated behind this boundary.

    Returns
    -------
    tuple[int, int]
        The delivery attempts for pending platform identity invitations.

    Raises
    ------
    InvitationDeliveryDependencyError
        If the operation encounters a invitation delivery dependency condition.
    ValueError
        If the supplied value cannot satisfy the documented contract.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_DELIVERY_BATCH:
        raise ValueError("Invitation delivery limit must be between 1 and 1000.")
    try:
        keyring = private_keyring or worker_invitation_private_keyring()
    except InvitationCryptoError as error:
        raise InvitationDeliveryDependencyError from error
    now = timezone.now()
    delivery_ids = list(
        _eligible_delivery_queryset(at=now)
        .order_by("available_at", "created_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    attempted = 0
    pending = 0
    for delivery_id in delivery_ids:
        try:
            status = deliver_platform_identity_invitation(
                delivery_id,
                private_keyring=keyring,
                adapter=adapter,
            )
        except InvitationDeliveryDependencyError:
            # One retired/missing envelope key must not starve unrelated
            # deliveries. Readiness separately blocks key retirement while a
            # live envelope still references it.
            pending += 1
            continue
        if status != PlatformIdentityDelivery.Status.PROCESSING:
            attempted += 1
        if status in (
            PlatformIdentityDelivery.Status.PENDING,
            PlatformIdentityDelivery.Status.PROCESSING,
            PlatformIdentityDelivery.Status.RETRYING,
        ):
            pending += 1
    return attempted, pending


__all__ = [
    "DeliveryAdapter",
    "InvitationDeliveryBacklogSnapshot",
    "InvitationDeliveryDependencyError",
    "InvitationDeliveryError",
    "InvitationDeliveryMessage",
    "deliver_pending_platform_identity_invitations",
    "deliver_platform_identity_invitation",
    "platform_identity_delivery_backlog_snapshot",
]
