"""Atomic platform account-invitation commands for Page 10."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from django.contrib.auth import password_validation
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.identity.invitation_crypto import (
    InvitationCryptoError,
    encrypt_invitation_payload,
)
from maru.identity.invitation_delivery_payload import (
    INVITATION_TOKEN_LENGTH,
    encode_invitation_delivery_payload,
    invitation_delivery_aad,
)
from maru.identity.invitation_inputs import (
    canonical_request_digest,
    normalize_invitation_display_name,
    normalize_invitation_email,
    normalize_invitation_login_handle,
    normalize_invitation_preferred_language,
    normalize_invitation_reason,
    validate_correlation_id,
    validate_invitation_expected_version,
    validate_retry_key,
    validate_source_channel,
)
from maru.identity.invitation_key_config import active_invitation_encryption_key
from maru.identity.invitation_token_keys import (
    InvitationTokenKeyConfigurationError,
    invitation_token_keyring,
)
from maru.identity.models import (
    Account,
    AccountSecurityEvent,
    IdentityChallenge,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformAccountInvitationCommandReceipt,
    PlatformAccountInvitationTransition,
    PlatformIdentityDelivery,
)
from maru.identity.services import enforce_abuse_limit

INVITATION_LIFETIME: Final = timedelta(days=7)
MAX_EXPIRY_BATCH: Final = 1_000
INVITATION_CONTRACT_VERSION: Final = "page10-invitations-v1"
MAX_INVITATION_PASSWORD_LENGTH: Final = 128
INVITATION_REQUEST_FINGERPRINT_LENGTH: Final = 64
INVITATION_CHALLENGE_ATTEMPT_LIMIT: Final = 10
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class InvitationCommandError(RuntimeError):
    """Signal invitation command."""

    reason_code = "account_invitation_command_failed"

    def __init__(
        self, message: str = "The account invitation could not be changed."
    ) -> None:
        """Initialize the InvitationCommandError instance.

        Parameters
        ----------
        message : str, default='The account invitation could not be changed.'
            The disclosure-safe message associated with the outcome.
        """
        super().__init__(message)


class InvitationAuthorizationDeniedError(InvitationCommandError):
    """Signal invitation authorization denied."""

    reason_code = "platform_administration_required"


class InvitationIdentityConflictError(InvitationCommandError):
    """Signal invitation identity conflict."""

    reason_code = "account_invitation_identity_unavailable"


class InvitationUnavailableError(InvitationCommandError):
    """Signal invitation unavailable."""

    reason_code = "account_invitation_unavailable"


class InvitationVersionConflictError(InvitationCommandError):
    """Signal invitation version conflict."""

    reason_code = "account_invitation_version_conflict"


class InvitationRetryConflictError(InvitationCommandError):
    """Signal invitation retry conflict."""

    reason_code = "account_invitation_retry_conflict"


class InvitationStateConflictError(InvitationCommandError):
    """Signal invitation state conflict."""

    reason_code = "account_invitation_state_conflict"


class InvitationChallengeInvalidError(InvitationCommandError):
    """Signal invitation challenge invalid."""

    reason_code = "account_invitation_challenge_invalid"

    def __init__(self) -> None:
        """Initialize the InvitationChallengeInvalidError instance."""
        super().__init__("The invitation code is invalid or has expired.")


class InvitationDependencyUnavailableError(InvitationCommandError):
    """Signal invitation dependency unavailable."""

    reason_code = "account_invitation_dependency_unavailable"


@dataclass(frozen=True, slots=True)
class AccountInvitationCommandResult:
    """Describe account invitation command result.

    Attributes
    ----------
    invitation
        The invitation retained in this immutable projection.
    receipt
        The immutable command receipt proving the accepted transition.
    replayed
        The replayed retained in this immutable projection.
    """

    invitation: PlatformAccountInvitation
    receipt: PlatformAccountInvitationCommandReceipt
    replayed: bool


@dataclass(frozen=True, slots=True)
class AcceptedAccountInvitationResult:
    """Describe accepted account invitation result.

    Attributes
    ----------
    account
        The platform account whose state or access is being evaluated.
    invitation
        The invitation retained in this immutable projection.
    receipt
        The immutable command receipt proving the accepted transition.
    replayed
        The replayed retained in this immutable projection.
    """

    account: Account
    invitation: PlatformAccountInvitation
    receipt: PlatformAccountInvitationCommandReceipt
    replayed: bool


def _retry_key_hash(retry_key: UUID) -> str:
    return hashlib.sha256(retry_key.bytes).hexdigest()


def _require_platform_actor(actor: Account) -> None:
    if (
        not isinstance(actor, Account)
        or actor.pk is None
        or not actor.is_active
        or not actor.is_platform_administrator
    ):
        raise InvitationAuthorizationDeniedError


def _lock_platform_actor(actor: Account) -> Account:
    persisted = Account.objects.select_for_update().filter(pk=actor.pk).first()
    if (
        persisted is None
        or not persisted.is_active
        or not persisted.is_platform_administrator
    ):
        raise InvitationAuthorizationDeniedError
    return persisted


def _lock_inventory_control() -> PlatformAccountInventoryControl:
    try:
        return PlatformAccountInventoryControl.objects.select_for_update().get(
            singleton=True
        )
    except PlatformAccountInventoryControl.DoesNotExist as error:
        raise InvitationDependencyUnavailableError from error


def _advance_inventory_control(
    control: PlatformAccountInventoryControl,
) -> None:
    # Account display-field writes advance this same fence in PostgreSQL.  A
    # command may therefore have changed the locked row through the Account
    # trigger since the object was loaded (create and accept both do).  Reload
    # before the command-level increment so the guarded update is contiguous.
    control.refresh_from_db(fields=("aggregate_version",))
    control.aggregate_version = int(control.aggregate_version) + 1
    control.save(update_fields=("aggregate_version", "updated_at"))


def _receipt_for_retry(
    *,
    control: PlatformAccountInventoryControl,
    actor: Account,
    retry_key: UUID,
) -> PlatformAccountInvitationCommandReceipt | None:
    return (
        PlatformAccountInvitationCommandReceipt.objects.select_related(
            "invitation",
            "invitation__account",
        )
        .filter(
            inventory_control=control,
            actor=actor,
            retry_key=retry_key,
        )
        .first()
    )


def _require_matching_receipt(
    *,
    receipt: PlatformAccountInvitationCommandReceipt,
    operation: str,
    request_digest: str,
    invitation_id: UUID | None = None,
) -> None:
    if (
        receipt.operation != operation
        or receipt.request_digest != request_digest
        or (invitation_id is not None and receipt.invitation_id != invitation_id)
    ):
        raise InvitationRetryConflictError


def _append_security_event(
    *,
    account: Account,
    event_type: str,
    detail_code: str,
    source_channel: str,
    occurred_at: datetime,
) -> None:
    AccountSecurityEvent.objects.create(
        account=account,
        event_type=event_type,
        outcome=AccountSecurityEvent.Outcome.SUCCEEDED,
        occurred_at=occurred_at,
        source_channel=source_channel,
        detail_code=detail_code,
    )


def _append_invitation_audit(
    *,
    actor: Account | None,
    invitation: PlatformAccountInvitation,
    operation: str,
    reason_code: str,
    changed_fields: tuple[str, ...],
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    occurred_at: datetime,
    retry_key: UUID | None = None,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind=("system" if actor is None else "account"),
            principal_id=(None if actor is None else actor.id),
            principal_context_id=None,
            organization_id=None,
            event_edition_id=None,
            capability_code=(
                "identity.accept_account_invitation"
                if operation == "identity.account_invitation.accept"
                else "identity.manage_account_invitations"
            ),
            operation=operation,
            target_type="identity.platform_account_invitation",
            target_id=invitation.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=("audit",),
            changed_fields=changed_fields,
            idempotency_key_hash=(
                _retry_key_hash(retry_key) if retry_key is not None else ""
            ),
            safe_metadata={"contract_version": INVITATION_CONTRACT_VERSION},
            retention_class="identity-restricted",
        ),
        occurred_at=occurred_at,
    )


def _create_transition(
    *,
    invitation: PlatformAccountInvitation,
    operation: str,
    actor: Account | None,
    reason: str,
    correlation_id: UUID,
    source_channel: str,
    occurred_at: datetime,
) -> PlatformAccountInvitationTransition:
    return PlatformAccountInvitationTransition.objects.create(
        invitation=invitation,
        version=invitation.aggregate_version,
        operation=operation,
        actor=actor,
        occurred_at=occurred_at,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


def _new_challenge_and_delivery(
    *,
    invitation: PlatformAccountInvitation,
    actor: Account,
    correlation_id: UUID,
    occurred_at: datetime,
) -> tuple[IdentityChallenge, PlatformIdentityDelivery]:
    raw_token = secrets.token_urlsafe(32)
    try:
        digest_keyring = invitation_token_keyring()
    except InvitationTokenKeyConfigurationError as error:
        raise InvitationDependencyUnavailableError from error
    challenge = IdentityChallenge.objects.create(
        id=uuid4(),
        account=invitation.account,
        purpose=IdentityChallenge.Purpose.ACCOUNT_INVITATION,
        token_digest=digest_keyring.digest(
            raw_token,
            purpose="account-invitation-challenge",
        ),
        token_digest_key_id=digest_keyring.active_key_id,
        email_snapshot=invitation.account.email,
        expires_at=invitation.expires_at,
        request_fingerprint=digest_keyring.digest(
            f"{actor.id}|{correlation_id}|{invitation.aggregate_version}",
            purpose="account-invitation-issuance",
        ),
        invitation=invitation,
        invitation_version=invitation.aggregate_version,
        delivery_status=IdentityChallenge.DeliveryStatus.SUPPRESSED,
    )
    aad = invitation_delivery_aad(
        invitation_id=invitation.id,
        challenge_id=challenge.id,
        invitation_version=invitation.aggregate_version,
        email=invitation.account.email,
    )
    try:
        envelope = encrypt_invitation_payload(
            payload=encode_invitation_delivery_payload(raw_token=raw_token),
            aad=aad,
            active_key=active_invitation_encryption_key(),
        )
    except InvitationCryptoError as error:
        raise InvitationDependencyUnavailableError from error
    delivery = PlatformIdentityDelivery.objects.create(
        invitation=invitation,
        challenge=challenge,
        status=PlatformIdentityDelivery.Status.PENDING,
        available_at=occurred_at,
        encryption_algorithm=envelope.encryption_algorithm,
        encryption_key_id=envelope.encryption_key_id,
        encrypted_payload=envelope.encrypted_payload,
        wrapped_data_key=envelope.wrapped_data_key,
        payload_nonce=envelope.payload_nonce,
        payload_aad_digest=envelope.payload_aad_digest,
    )
    invitation.current_challenge = challenge
    invitation.save(update_fields=("current_challenge", "updated_at"))
    return challenge, delivery


def _invalidate_challenge(
    challenge: IdentityChallenge | None,
    *,
    reason: str,
    occurred_at: datetime,
) -> None:
    if (
        challenge is None
        or challenge.consumed_at is not None
        or challenge.invalidated_at is not None
    ):
        return
    challenge.invalidated_at = occurred_at
    challenge.invalidation_reason = reason
    challenge.save(
        update_fields=("invalidated_at", "invalidation_reason", "updated_at")
    )


def _destroy_delivery(
    delivery: PlatformIdentityDelivery | None,
    *,
    reason: str,
    occurred_at: datetime,
    safe_error_code: str,
) -> None:
    if delivery is None:
        return
    if delivery.payload_destroyed_at is not None:
        return
    delivery.encryption_algorithm = ""
    delivery.encryption_key_id = ""
    delivery.encrypted_payload = None
    delivery.wrapped_data_key = None
    delivery.payload_nonce = None
    delivery.payload_aad_digest = ""
    delivery.payload_destroyed_at = occurred_at
    delivery.payload_destruction_reason = reason
    if delivery.status != PlatformIdentityDelivery.Status.DELIVERED:
        delivery.cancellation_requested_at = occurred_at
        delivery.cancellation_code = safe_error_code
        if delivery.status == PlatformIdentityDelivery.Status.PROCESSING:
            # The provider call is outside the database transaction. Preserve its
            # lease so the worker can classify the real late result durably.
            delivery.safe_error_code = ""
        else:
            delivery.status = PlatformIdentityDelivery.Status.CANCELLED
            delivery.safe_error_code = safe_error_code
            delivery.cancelled_at = occurred_at
            delivery.claimed_at = None
            delivery.lease_expires_at = None
            delivery.lease_token = None
            delivery.next_retry_at = None
    if (
        delivery.reconciliation_state
        == PlatformIdentityDelivery.ReconciliationState.REQUIRED
    ):
        delivery.reconciliation_state = (
            PlatformIdentityDelivery.ReconciliationState.RESOLVED
        )
        delivery.reconciled_at = occurred_at
        delivery.reconciliation_code = safe_error_code
    delivery.aggregate_version += 1
    delivery.save(
        update_fields=(
            "aggregate_version",
            "encryption_algorithm",
            "encryption_key_id",
            "encrypted_payload",
            "wrapped_data_key",
            "payload_nonce",
            "payload_aad_digest",
            "payload_destroyed_at",
            "payload_destruction_reason",
            "status",
            "safe_error_code",
            "claimed_at",
            "lease_expires_at",
            "lease_token",
            "next_retry_at",
            "reconciliation_state",
            "reconciled_at",
            "reconciliation_code",
            "cancellation_requested_at",
            "cancellation_code",
            "cancelled_at",
            "updated_at",
        )
    )


def _locked_invitation(
    invitation_id: UUID,
) -> PlatformAccountInvitation:
    invitation = (
        PlatformAccountInvitation.objects.select_for_update(of=("self",))
        .select_related("created_by", "current_challenge")
        .filter(id=invitation_id)
        .first()
    )
    if invitation is None:
        raise InvitationUnavailableError
    return invitation


def _locked_current_delivery(
    invitation: PlatformAccountInvitation,
) -> PlatformIdentityDelivery | None:
    if invitation.current_challenge_id is None:
        return None
    return (
        PlatformIdentityDelivery.objects.select_for_update()
        .filter(
            invitation=invitation,
            challenge_id=invitation.current_challenge_id,
        )
        .first()
    )


def create_platform_account_invitation(
    *,
    actor: Account,
    email: object,
    login_handle: object | None,
    display_name: object | None,
    preferred_language: object | None,
    reason: object,
    expected_version: object,
    retry_key: object,
    correlation_id: object,
    request_id: UUID | None = None,
    source_channel: object = "service",
) -> AccountInvitationCommandResult:
    """Reserve only one inactive person identity and queue its owned invitation.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    email : object
        The normalized email address used for delivery or identity matching.
    login_handle : object | None
        The login handle applied within the audited domain transition.
    display_name : object | None
        The human-readable display name shown to authorized readers.
    preferred_language : object | None
        The supported language code used for preferred.
    reason : object
        The operator-supplied rationale recorded with the change.
    expected_version : object
        The aggregate version required for optimistic concurrency control.
    retry_key : object
        The stable key that makes an exact command retry idempotent.
    correlation_id : object
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : object, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    AccountInvitationCommandResult
        The newly created AccountInvitationCommandResult.

    Raises
    ------
    InvitationIdentityConflictError
        If the operation encounters a invitation identity conflict condition.
    InvitationVersionConflictError
        If the supplied aggregate version is stale.
    """
    _require_platform_actor(actor)
    normalized_email = normalize_invitation_email(email)
    normalized_handle = normalize_invitation_login_handle(login_handle)
    normalized_name = normalize_invitation_display_name(display_name)
    normalized_language = normalize_invitation_preferred_language(preferred_language)
    normalized_reason = normalize_invitation_reason(reason)
    version = validate_invitation_expected_version(expected_version)
    key = validate_retry_key(retry_key)
    correlation = validate_correlation_id(correlation_id)
    channel = validate_source_channel(source_channel)
    if version != 0:
        raise InvitationVersionConflictError
    request_digest = canonical_request_digest(
        {
            "operation": "create",
            "email": normalized_email,
            "login_handle": normalized_handle or "",
            "display_name": normalized_name or "",
            "preferred_language": normalized_language,
            "reason": normalized_reason,
            "expected_version": version,
        }
    )

    with transaction.atomic():
        locked_actor = _lock_platform_actor(actor)
        control = _lock_inventory_control()
        existing_receipt = _receipt_for_retry(
            control=control,
            actor=locked_actor,
            retry_key=key,
        )
        if existing_receipt is not None:
            _require_matching_receipt(
                receipt=existing_receipt,
                operation=PlatformAccountInvitationCommandReceipt.Operation.CREATE,
                request_digest=request_digest,
            )
            return AccountInvitationCommandResult(
                invitation=existing_receipt.invitation,
                receipt=existing_receipt,
                replayed=True,
            )
        identity_conflict = Account.objects.filter(email__iexact=normalized_email)
        if normalized_handle:
            identity_conflict = identity_conflict | Account.objects.filter(
                login_handle__iexact=normalized_handle
            )
        if identity_conflict.exists():
            raise InvitationIdentityConflictError
        account = Account(
            email=normalized_email,
            login_handle=normalized_handle or "",
            display_name=normalized_name or "",
            preferred_language=normalized_language,
            account_kind=Account.Kind.PERSON,
            is_active=False,
            is_staff=False,
            is_superuser=False,
            email_verified_at=None,
        )
        account.set_unusable_password()
        try:
            account.full_clean()
            account.save()
        except (IntegrityError, ValidationError) as error:
            raise InvitationIdentityConflictError from error
        occurred_at = timezone.now()
        invitation = PlatformAccountInvitation.objects.create(
            account=account,
            status=PlatformAccountInvitation.Status.PENDING,
            aggregate_version=1,
            expires_at=occurred_at + INVITATION_LIFETIME,
            last_transition_at=occurred_at,
            created_by=locked_actor,
        )
        account.invitation_provisioning_origin = invitation
        account.save(update_fields=("invitation_provisioning_origin",))
        _new_challenge_and_delivery(
            invitation=invitation,
            actor=locked_actor,
            correlation_id=correlation,
            occurred_at=occurred_at,
        )
        _create_transition(
            invitation=invitation,
            operation=PlatformAccountInvitationTransition.Operation.CREATED,
            actor=locked_actor,
            reason=normalized_reason,
            correlation_id=correlation,
            source_channel=channel,
            occurred_at=occurred_at,
        )
        _advance_inventory_control(control)
        receipt = PlatformAccountInvitationCommandReceipt.objects.create(
            inventory_control=control,
            invitation=invitation,
            actor=locked_actor,
            operation=PlatformAccountInvitationCommandReceipt.Operation.CREATE,
            retry_key=key,
            request_digest=request_digest,
            expected_version=0,
            result_version=1,
            correlation_id=correlation,
            source_channel=channel,
        )
        _append_security_event(
            account=account,
            event_type=AccountSecurityEvent.EventType.ACCOUNT_INVITATION_CREATED,
            detail_code="platform_account_invitation_created",
            source_channel=channel,
            occurred_at=occurred_at,
        )
        _append_invitation_audit(
            actor=locked_actor,
            invitation=invitation,
            operation="identity.account_invitation.create",
            reason_code="platform_administration",
            changed_fields=("account", "invitation", "challenge", "delivery"),
            correlation_id=correlation,
            request_id=request_id,
            source_channel=channel,
            occurred_at=occurred_at,
            retry_key=key,
        )
        return AccountInvitationCommandResult(
            invitation=invitation,
            receipt=receipt,
            replayed=False,
        )


def reissue_platform_account_invitation(
    *,
    actor: Account,
    invitation_id: UUID,
    expected_version: object,
    reason: object,
    retry_key: object,
    correlation_id: object,
    request_id: UUID | None = None,
    source_channel: object = "service",
) -> AccountInvitationCommandResult:
    """Return reissue platform account invitation.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    invitation_id : UUID
        The identifier of the invitation.
    expected_version : object
        The aggregate version required for optimistic concurrency.
    reason : object
        The operator-supplied reason for the operation.
    retry_key : object
        The stable key used to retry the operation safely.
    correlation_id : object
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : object, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    AccountInvitationCommandResult
        The account invitation command result.

    Raises
    ------
    InvitationStateConflictError
        If the target lifecycle state does not permit the transition.
    InvitationVersionConflictError
        If the supplied aggregate version is stale.
    """
    _require_platform_actor(actor)
    version = validate_invitation_expected_version(expected_version)
    normalized_reason = normalize_invitation_reason(reason)
    key = validate_retry_key(retry_key)
    correlation = validate_correlation_id(correlation_id)
    channel = validate_source_channel(source_channel)
    request_digest = canonical_request_digest(
        {
            "operation": "reissue",
            "invitation_id": invitation_id,
            "expected_version": version,
            "reason": normalized_reason,
        }
    )
    with transaction.atomic():
        locked_actor = _lock_platform_actor(actor)
        control = _lock_inventory_control()
        invitation = _locked_invitation(invitation_id)
        existing_receipt = _receipt_for_retry(
            control=control,
            actor=locked_actor,
            retry_key=key,
        )
        if existing_receipt is not None:
            _require_matching_receipt(
                receipt=existing_receipt,
                operation=PlatformAccountInvitationCommandReceipt.Operation.REISSUE,
                request_digest=request_digest,
                invitation_id=invitation.id,
            )
            return AccountInvitationCommandResult(
                invitation=existing_receipt.invitation,
                receipt=existing_receipt,
                replayed=True,
            )
        if version != invitation.aggregate_version:
            raise InvitationVersionConflictError
        if invitation.status in (
            PlatformAccountInvitation.Status.ACCEPTED,
            PlatformAccountInvitation.Status.REVOKED,
        ):
            raise InvitationStateConflictError
        occurred_at = timezone.now()
        old_delivery = _locked_current_delivery(invitation)
        _invalidate_challenge(
            invitation.current_challenge,
            reason="superseded_by_reissue",
            occurred_at=occurred_at,
        )
        _destroy_delivery(
            old_delivery,
            reason=PlatformIdentityDelivery.PayloadDestructionReason.SUPERSEDED,
            occurred_at=occurred_at,
            safe_error_code="invitation_superseded",
        )
        invitation.current_challenge = None
        invitation.aggregate_version = version + 1
        invitation.status = PlatformAccountInvitation.Status.PENDING
        invitation.expires_at = occurred_at + INVITATION_LIFETIME
        invitation.last_transition_at = occurred_at
        invitation.accepted_at = None
        invitation.revoked_at = None
        invitation.expired_at = None
        invitation.save(
            update_fields=(
                "current_challenge",
                "aggregate_version",
                "status",
                "expires_at",
                "last_transition_at",
                "accepted_at",
                "revoked_at",
                "expired_at",
                "updated_at",
            )
        )
        _new_challenge_and_delivery(
            invitation=invitation,
            actor=locked_actor,
            correlation_id=correlation,
            occurred_at=occurred_at,
        )
        _create_transition(
            invitation=invitation,
            operation=PlatformAccountInvitationTransition.Operation.REISSUED,
            actor=locked_actor,
            reason=normalized_reason,
            correlation_id=correlation,
            source_channel=channel,
            occurred_at=occurred_at,
        )
        _advance_inventory_control(control)
        receipt = PlatformAccountInvitationCommandReceipt.objects.create(
            inventory_control=control,
            invitation=invitation,
            actor=locked_actor,
            operation=PlatformAccountInvitationCommandReceipt.Operation.REISSUE,
            retry_key=key,
            request_digest=request_digest,
            expected_version=version,
            result_version=version + 1,
            correlation_id=correlation,
            source_channel=channel,
        )
        _append_security_event(
            account=invitation.account,
            event_type=AccountSecurityEvent.EventType.ACCOUNT_INVITATION_REISSUED,
            detail_code="platform_account_invitation_reissued",
            source_channel=channel,
            occurred_at=occurred_at,
        )
        _append_invitation_audit(
            actor=locked_actor,
            invitation=invitation,
            operation="identity.account_invitation.reissue",
            reason_code="platform_administration",
            changed_fields=("invitation", "challenge", "delivery"),
            correlation_id=correlation,
            request_id=request_id,
            source_channel=channel,
            occurred_at=occurred_at,
            retry_key=key,
        )
        return AccountInvitationCommandResult(
            invitation=invitation,
            receipt=receipt,
            replayed=False,
        )


def revoke_platform_account_invitation(
    *,
    actor: Account,
    invitation_id: UUID,
    expected_version: object,
    reason: object,
    retry_key: object,
    correlation_id: object,
    request_id: UUID | None = None,
    source_channel: object = "service",
) -> AccountInvitationCommandResult:
    """Revoke platform account invitation.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    invitation_id : UUID
        The identifier of the invitation.
    expected_version : object
        The aggregate version required for optimistic concurrency.
    reason : object
        The operator-supplied reason for the operation.
    retry_key : object
        The stable key used to retry the operation safely.
    correlation_id : object
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : object, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    AccountInvitationCommandResult
        The account invitation command result.

    Raises
    ------
    InvitationStateConflictError
        If the target lifecycle state does not permit the transition.
    InvitationVersionConflictError
        If the supplied aggregate version is stale.
    """
    _require_platform_actor(actor)
    version = validate_invitation_expected_version(expected_version)
    normalized_reason = normalize_invitation_reason(reason)
    key = validate_retry_key(retry_key)
    correlation = validate_correlation_id(correlation_id)
    channel = validate_source_channel(source_channel)
    request_digest = canonical_request_digest(
        {
            "operation": "revoke",
            "invitation_id": invitation_id,
            "expected_version": version,
            "reason": normalized_reason,
        }
    )
    with transaction.atomic():
        locked_actor = _lock_platform_actor(actor)
        control = _lock_inventory_control()
        invitation = _locked_invitation(invitation_id)
        existing_receipt = _receipt_for_retry(
            control=control,
            actor=locked_actor,
            retry_key=key,
        )
        if existing_receipt is not None:
            _require_matching_receipt(
                receipt=existing_receipt,
                operation=PlatformAccountInvitationCommandReceipt.Operation.REVOKE,
                request_digest=request_digest,
                invitation_id=invitation.id,
            )
            return AccountInvitationCommandResult(
                invitation=existing_receipt.invitation,
                receipt=existing_receipt,
                replayed=True,
            )
        if version != invitation.aggregate_version:
            raise InvitationVersionConflictError
        if invitation.status != PlatformAccountInvitation.Status.PENDING:
            raise InvitationStateConflictError
        occurred_at = timezone.now()
        delivery = _locked_current_delivery(invitation)
        _invalidate_challenge(
            invitation.current_challenge,
            reason="invitation_revoked",
            occurred_at=occurred_at,
        )
        _destroy_delivery(
            delivery,
            reason=PlatformIdentityDelivery.PayloadDestructionReason.REVOKED,
            occurred_at=occurred_at,
            safe_error_code="invitation_revoked",
        )
        invitation.current_challenge = None
        invitation.aggregate_version = version + 1
        invitation.status = PlatformAccountInvitation.Status.REVOKED
        invitation.last_transition_at = occurred_at
        invitation.accepted_at = None
        invitation.revoked_at = occurred_at
        invitation.expired_at = None
        invitation.save(
            update_fields=(
                "current_challenge",
                "aggregate_version",
                "status",
                "last_transition_at",
                "accepted_at",
                "revoked_at",
                "expired_at",
                "updated_at",
            )
        )
        _create_transition(
            invitation=invitation,
            operation=PlatformAccountInvitationTransition.Operation.REVOKED,
            actor=locked_actor,
            reason=normalized_reason,
            correlation_id=correlation,
            source_channel=channel,
            occurred_at=occurred_at,
        )
        _advance_inventory_control(control)
        receipt = PlatformAccountInvitationCommandReceipt.objects.create(
            inventory_control=control,
            invitation=invitation,
            actor=locked_actor,
            operation=PlatformAccountInvitationCommandReceipt.Operation.REVOKE,
            retry_key=key,
            request_digest=request_digest,
            expected_version=version,
            result_version=version + 1,
            correlation_id=correlation,
            source_channel=channel,
        )
        _append_security_event(
            account=invitation.account,
            event_type=AccountSecurityEvent.EventType.ACCOUNT_INVITATION_REVOKED,
            detail_code="platform_account_invitation_revoked",
            source_channel=channel,
            occurred_at=occurred_at,
        )
        _append_invitation_audit(
            actor=locked_actor,
            invitation=invitation,
            operation="identity.account_invitation.revoke",
            reason_code="platform_administration",
            changed_fields=("invitation", "challenge", "delivery"),
            correlation_id=correlation,
            request_id=request_id,
            source_channel=channel,
            occurred_at=occurred_at,
            retry_key=key,
        )
        return AccountInvitationCommandResult(
            invitation=invitation,
            receipt=receipt,
            replayed=False,
        )


def _validate_acceptance_controls(
    *,
    raw_token: str,
    new_password: str,
    retry_key: object,
    correlation_id: object,
    request_fingerprint: str,
    source_channel: object,
) -> tuple[UUID, UUID, str]:
    if not isinstance(raw_token, str) or len(raw_token) != INVITATION_TOKEN_LENGTH:
        raise InvitationChallengeInvalidError
    if (
        not isinstance(new_password, str)
        or len(new_password) > MAX_INVITATION_PASSWORD_LENGTH
    ):
        raise ValidationError(
            {"new_password": "Enter a password of at most 128 characters."},
            code="invitation_password_invalid",
        )
    key = validate_retry_key(retry_key)
    correlation = validate_correlation_id(correlation_id)
    channel = validate_source_channel(source_channel)
    if (
        not isinstance(request_fingerprint, str)
        or len(request_fingerprint) != INVITATION_REQUEST_FINGERPRINT_LENGTH
        or _SHA256_PATTERN.fullmatch(request_fingerprint) is None
    ):
        raise InvitationChallengeInvalidError
    enforce_abuse_limit(
        flow="account_invitation_acceptance",
        subject_digest=request_fingerprint,
    )
    try:
        digest_keyring = invitation_token_keyring()
    except InvitationTokenKeyConfigurationError as error:
        raise InvitationDependencyUnavailableError from error
    enforce_abuse_limit(
        flow="account_invitation_acceptance_token",
        subject_digest=digest_keyring.digest(
            raw_token,
            purpose="account-invitation-abuse-subject",
        ),
    )
    return key, correlation, channel


def accept_platform_account_invitation(
    *,
    raw_token: str,
    new_password: str,
    retry_key: object,
    correlation_id: object,
    request_fingerprint: str,
    request_id: UUID | None = None,
    source_channel: object = "service",
) -> AcceptedAccountInvitationResult:
    """Accept platform account invitation.

    Parameters
    ----------
    raw_token : str
        The untrusted token supplied by the caller.
    new_password : str
        The new password applied within the audited domain transition.
    retry_key : object
        The stable key used to retry the operation safely.
    correlation_id : object
        The correlation identifier for audit tracing.
    request_fingerprint : str
        The request fingerprint applied within the audited domain transition.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : object, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    AcceptedAccountInvitationResult
        The accepted account invitation result.

    Raises
    ------
    InvitationChallengeInvalidError
        If the operation encounters a invitation challenge invalid condition.
    InvitationDependencyUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    InvitationRetryConflictError
        If a retry key is reused with different command intent.
    InvitationStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    key, correlation, channel = _validate_acceptance_controls(
        raw_token=raw_token,
        new_password=new_password,
        retry_key=retry_key,
        correlation_id=correlation_id,
        request_fingerprint=request_fingerprint,
        source_channel=source_channel,
    )
    try:
        digest_candidates = invitation_token_keyring().candidates(
            raw_token,
            purpose="account-invitation-challenge",
        )
    except InvitationTokenKeyConfigurationError as error:
        raise InvitationDependencyUnavailableError from error
    digest_query = Q()
    for key_id, token_digest in digest_candidates:
        digest_query |= Q(
            token_digest_key_id=key_id,
            token_digest=token_digest,
        )
    with transaction.atomic():
        control = _lock_inventory_control()
        challenge = (
            IdentityChallenge.objects.select_for_update()
            .filter(
                digest_query,
                purpose=IdentityChallenge.Purpose.ACCOUNT_INVITATION,
            )
            .first()
        )
        if challenge is None or challenge.invitation_id is None:
            raise InvitationChallengeInvalidError
        invitation = _locked_invitation(challenge.invitation_id)
        account = Account.objects.select_for_update().get(id=challenge.account_id)
        request_digest = canonical_request_digest(
            {
                "operation": "accept",
                "invitation_id": invitation.id,
                "challenge_id": challenge.id,
                "expected_version": challenge.invitation_version or 0,
            }
        )
        existing_receipt = _receipt_for_retry(
            control=control,
            actor=account,
            retry_key=key,
        )
        if existing_receipt is not None:
            _require_matching_receipt(
                receipt=existing_receipt,
                operation=PlatformAccountInvitationCommandReceipt.Operation.ACCEPT,
                request_digest=request_digest,
                invitation_id=invitation.id,
            )
            if invitation.status != PlatformAccountInvitation.Status.ACCEPTED:
                raise InvitationStateConflictError
            if not check_password(new_password, account.password):
                raise InvitationRetryConflictError
            return AcceptedAccountInvitationResult(
                account=account,
                invitation=invitation,
                receipt=existing_receipt,
                replayed=True,
            )
        occurred_at = timezone.now()
        if (
            challenge.consumed_at is not None
            or challenge.invalidated_at is not None
            or challenge.expires_at <= occurred_at
            or challenge.attempt_count >= INVITATION_CHALLENGE_ATTEMPT_LIMIT
            or invitation.status != PlatformAccountInvitation.Status.PENDING
            or invitation.expires_at <= occurred_at
            or invitation.current_challenge_id != challenge.id
            or challenge.invitation_version != invitation.aggregate_version
            or challenge.email_snapshot.casefold() != account.email.casefold()
            or account.account_kind != Account.Kind.PERSON
            or account.is_active
            or account.is_staff
            or account.is_superuser
            or account.email_verified_at is not None
            or account.has_usable_password()
        ):
            raise InvitationChallengeInvalidError
        password_validation.validate_password(new_password, user=account)
        previous_version = invitation.aggregate_version
        challenge.attempt_count += 1
        challenge.consumed_at = occurred_at
        challenge.save(update_fields=("attempt_count", "consumed_at", "updated_at"))
        account.set_password(new_password)
        account.is_active = True
        account.email_verified_at = occurred_at
        account.save(update_fields=("password", "is_active", "email_verified_at"))
        invitation.current_challenge = None
        invitation.aggregate_version = previous_version + 1
        invitation.status = PlatformAccountInvitation.Status.ACCEPTED
        invitation.last_transition_at = occurred_at
        invitation.accepted_at = occurred_at
        invitation.revoked_at = None
        invitation.expired_at = None
        invitation.save(
            update_fields=(
                "current_challenge",
                "aggregate_version",
                "status",
                "last_transition_at",
                "accepted_at",
                "revoked_at",
                "expired_at",
                "updated_at",
            )
        )
        delivery = (
            PlatformIdentityDelivery.objects.select_for_update()
            .filter(challenge=challenge)
            .first()
        )
        _destroy_delivery(
            delivery,
            reason=PlatformIdentityDelivery.PayloadDestructionReason.SUPERSEDED,
            occurred_at=occurred_at,
            safe_error_code="invitation_consumed",
        )
        _create_transition(
            invitation=invitation,
            operation=PlatformAccountInvitationTransition.Operation.ACCEPTED,
            actor=account,
            reason="Recipient accepted the account invitation.",
            correlation_id=correlation,
            source_channel=channel,
            occurred_at=occurred_at,
        )
        _advance_inventory_control(control)
        receipt = PlatformAccountInvitationCommandReceipt.objects.create(
            inventory_control=control,
            invitation=invitation,
            actor=account,
            operation=PlatformAccountInvitationCommandReceipt.Operation.ACCEPT,
            retry_key=key,
            request_digest=request_digest,
            expected_version=previous_version,
            result_version=previous_version + 1,
            correlation_id=correlation,
            source_channel=channel,
        )
        _append_security_event(
            account=account,
            event_type=AccountSecurityEvent.EventType.ACCOUNT_INVITATION_ACCEPTED,
            detail_code="platform_account_invitation_accepted",
            source_channel=channel,
            occurred_at=occurred_at,
        )
        _append_invitation_audit(
            actor=account,
            invitation=invitation,
            operation="identity.account_invitation.accept",
            reason_code="invitation_challenge_accepted",
            changed_fields=("account", "invitation", "challenge", "delivery"),
            correlation_id=correlation,
            request_id=request_id,
            source_channel=channel,
            occurred_at=occurred_at,
            retry_key=key,
        )
        return AcceptedAccountInvitationResult(
            account=account,
            invitation=invitation,
            receipt=receipt,
            replayed=False,
        )


def expire_platform_account_invitations(
    *,
    correlation_id: object,
    limit: int = 100,
    source_channel: object = "scheduler",
) -> int:
    """Expire platform account invitations.

    Parameters
    ----------
    correlation_id : object
        The correlation identifier for audit tracing.
    limit : int, default=100
        The maximum number of records to process.
    source_channel : object, default='scheduler'
        The trusted channel that initiated the operation.

    Returns
    -------
    int
        The effective numeric value for expire platform account invitations.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    correlation = validate_correlation_id(correlation_id)
    channel = validate_source_channel(source_channel)
    if type(limit) is not int or not 1 <= limit <= MAX_EXPIRY_BATCH:
        raise ValidationError(
            {"limit": "Choose an expiry batch from 1 through 1000."},
            code="invitation_expiry_limit_invalid",
        )
    now = timezone.now()
    invitation_ids = list(
        PlatformAccountInvitation.objects.filter(
            status=PlatformAccountInvitation.Status.PENDING,
            expires_at__lte=now,
        )
        .order_by("expires_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    expired_count = 0
    for invitation_id in invitation_ids:
        with transaction.atomic():
            control = _lock_inventory_control()
            invitation = _locked_invitation(invitation_id)
            occurred_at = timezone.now()
            if (
                invitation.status != PlatformAccountInvitation.Status.PENDING
                or invitation.expires_at > occurred_at
            ):
                continue
            delivery = _locked_current_delivery(invitation)
            _invalidate_challenge(
                invitation.current_challenge,
                reason="invitation_expired",
                occurred_at=occurred_at,
            )
            _destroy_delivery(
                delivery,
                reason=PlatformIdentityDelivery.PayloadDestructionReason.EXPIRED,
                occurred_at=occurred_at,
                safe_error_code="invitation_expired",
            )
            invitation.current_challenge = None
            invitation.aggregate_version += 1
            invitation.status = PlatformAccountInvitation.Status.EXPIRED
            invitation.last_transition_at = occurred_at
            invitation.accepted_at = None
            invitation.revoked_at = None
            invitation.expired_at = occurred_at
            invitation.save(
                update_fields=(
                    "current_challenge",
                    "aggregate_version",
                    "status",
                    "last_transition_at",
                    "accepted_at",
                    "revoked_at",
                    "expired_at",
                    "updated_at",
                )
            )
            _create_transition(
                invitation=invitation,
                operation=PlatformAccountInvitationTransition.Operation.EXPIRED,
                actor=None,
                reason="Invitation expired under the configured lifetime policy.",
                correlation_id=correlation,
                source_channel=channel,
                occurred_at=occurred_at,
            )
            _advance_inventory_control(control)
            _append_security_event(
                account=invitation.account,
                event_type=AccountSecurityEvent.EventType.ACCOUNT_INVITATION_EXPIRED,
                detail_code="platform_account_invitation_expired",
                source_channel=channel,
                occurred_at=occurred_at,
            )
            _append_invitation_audit(
                actor=None,
                invitation=invitation,
                operation="identity.account_invitation.expire",
                reason_code="invitation_lifetime_elapsed",
                changed_fields=("invitation", "challenge", "delivery"),
                correlation_id=correlation,
                request_id=None,
                source_channel=channel,
                occurred_at=occurred_at,
            )
            expired_count += 1
    return expired_count


__all__ = [
    "INVITATION_LIFETIME",
    "AcceptedAccountInvitationResult",
    "AccountInvitationCommandResult",
    "InvitationAuthorizationDeniedError",
    "InvitationChallengeInvalidError",
    "InvitationCommandError",
    "InvitationDependencyUnavailableError",
    "InvitationIdentityConflictError",
    "InvitationRetryConflictError",
    "InvitationStateConflictError",
    "InvitationUnavailableError",
    "InvitationVersionConflictError",
    "accept_platform_account_invitation",
    "create_platform_account_invitation",
    "expire_platform_account_invitations",
    "reissue_platform_account_invitation",
    "revoke_platform_account_invitation",
]
