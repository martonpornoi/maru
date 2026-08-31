"""Credential commands and signed offline relay reconciliation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from maru.accreditation.adoption import profile_allows_offline_check_in_relay
from maru.accreditation.models import (
    Credential,
    CredentialEvent,
    OfflineCheckInOperation,
    OfflineCredentialManifest,
    RelayDevice,
)
from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import decide, resolve_edition_target
from maru.authorization.services import AuthorizationDenied
from maru.events.queries import edition_adoption_profile_reference
from maru.registration.models import CheckInRecord, Registration
from maru.registration.services import (
    _append_timeline,
    _publish_registration_transition,
)

if TYPE_CHECKING:
    from uuid import UUID

    from maru.identity.models import Account

MANIFEST_LIFETIME = timedelta(hours=12)


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    """Describe issued credential.

    Attributes
    ----------
    credential
        The credential retained in this immutable projection.
    raw_token
        The opaque raw token supplied by the caller.
    """

    credential: Credential
    raw_token: str | None


def _credential_digest(raw_token: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"credential:{raw_token}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _require(
    *,
    actor: Account,
    capability_code: str,
    organization_id: UUID,
    edition_id: UUID,
) -> tuple[str, ...]:
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "Accreditation operation is unavailable.",
            reason_code=decision.reason_code,
        )
    return tuple(sorted(decision.obligations))


def _audit(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    operation: str,
    target_type: str,
    target_id: UUID,
    reason_code: str,
    obligations: tuple[str, ...],
    correlation_id: UUID,
    changed_fields: tuple[str, ...],
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="api",
            obligations=obligations,
            changed_fields=changed_fields,
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="security-extended",
        )
    )


def issue_credential(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
    reason: str,
    correlation_id: UUID,
) -> IssuedCredential:
    """Issue or replace an attendee credential within one edition.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    registration_id : UUID
        The identifier of the registration.
    reason : str
        The operator-supplied reason for the operation.
    correlation_id : UUID
        The correlation identifier for audit tracing.

    Returns
    -------
    IssuedCredential
        The persisted credential and, only when explicitly enabled for tests,
        its one-time plaintext token.

    Raises
    ------
    ValidationError
        If the reason is empty or the registration lacks an effective active
        admission entitlement.

    Notes
    -----
    The registration and current credential are locked in one transaction. A
    reissue first marks the current credential as replaced, then appends the
    credential event and audit evidence for the successor.

    Warnings
    --------
    The plaintext credential token is one-time sensitive material. Production
    callers receive ``None`` unless the test-only exposure setting is enabled.
    """
    obligations = _require(
        actor=actor,
        capability_code="accreditation.issue",
        organization_id=organization_id,
        edition_id=edition_id,
    )
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError(
            "Credential issuance requires a reason.",
            code="credential_issue_reason_required",
        )
    issued_at = timezone.now()
    with transaction.atomic():
        registration = (
            Registration.objects.select_for_update()
            .select_related("account")
            .get(
                id=registration_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        if (
            registration.state
            not in (
                Registration.State.CONFIRMED,
                Registration.State.CHECKED_IN,
            )
            or not registration.entitlements.filter(status="active").exists()
        ):
            raise ValidationError(
                "An active admission entitlement is required.",
                code="credential_entitlement_required",
            )
        current = (
            Credential.objects.select_for_update()
            .filter(
                registration=registration,
                status=Credential.Status.ISSUED,
            )
            .first()
        )
        next_sequence = (
            Credential.objects.filter(registration=registration).aggregate(
                value=Max("issue_sequence")
            )["value"]
            or 0
        ) + 1
        if current is not None:
            current.status = Credential.Status.REPLACED
            current.revoked_at = issued_at
            current.revoked_by_id = actor.id
            current.revocation_reason = normalized_reason
            current.save(
                update_fields=(
                    "status",
                    "revoked_at",
                    "revoked_by_id",
                    "revocation_reason",
                    "updated_at",
                )
            )
            event_kind = CredentialEvent.Kind.REPRINTED
        else:
            event_kind = CredentialEvent.Kind.ISSUED
        raw_token = secrets.token_urlsafe(32)
        public_id = secrets.token_hex(8).upper()
        credential = Credential.objects.create(
            registration=registration,
            organization_id=organization_id,
            edition_id=edition_id,
            account_id=registration.account_id,
            public_id=public_id,
            token_digest=_credential_digest(raw_token),
            issue_sequence=next_sequence,
            label_snapshot=registration.product_name_snapshot,
            issued_at=issued_at,
            issued_by_id=actor.id,
        )
        CredentialEvent.objects.create(
            credential=credential,
            organization_id=organization_id,
            edition_id=edition_id,
            kind=event_kind,
            occurred_at=issued_at,
            actor_kind="account",
            actor_id=actor.id,
            reason_code="credential_issued",
        )
        _audit(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="accreditation.issue",
            operation="accreditation.credential.issue",
            target_type="accreditation.credential",
            target_id=credential.id,
            reason_code="credential_issued",
            obligations=obligations,
            correlation_id=correlation_id,
            changed_fields=("credential", "credential_event"),
        )
        return IssuedCredential(
            credential=credential,
            raw_token=(
                raw_token if settings.MARU_EXPOSE_TEST_CREDENTIAL_TOKENS else None
            ),
        )


def revoke_credential(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    credential_id: UUID,
    reason: str,
    correlation_id: UUID,
) -> Credential:
    """Revoke credential.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    credential_id : UUID
        The identifier of the credential.
    reason : str
        The operator-supplied reason for the operation.
    correlation_id : UUID
        The correlation identifier for audit tracing.

    Returns
    -------
    Credential
        The updated Credential after the transition commits.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    obligations = _require(
        actor=actor,
        capability_code="accreditation.revoke",
        organization_id=organization_id,
        edition_id=edition_id,
    )
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError(
            "Credential revocation requires a reason.",
            code="credential_revoke_reason_required",
        )
    revoked_at = timezone.now()
    with transaction.atomic():
        credential = Credential.objects.select_for_update().get(
            id=credential_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if credential.status != Credential.Status.ISSUED:
            return credential
        credential.status = Credential.Status.REVOKED
        credential.revoked_at = revoked_at
        credential.revoked_by_id = actor.id
        credential.revocation_reason = normalized_reason
        credential.save(
            update_fields=(
                "status",
                "revoked_at",
                "revoked_by_id",
                "revocation_reason",
                "updated_at",
            )
        )
        CredentialEvent.objects.create(
            credential=credential,
            organization_id=organization_id,
            edition_id=edition_id,
            kind=CredentialEvent.Kind.REVOKED,
            occurred_at=revoked_at,
            actor_kind="account",
            actor_id=actor.id,
            reason_code="credential_revoked",
        )
        _audit(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="accreditation.revoke",
            operation="accreditation.credential.revoke",
            target_type="accreditation.credential",
            target_id=credential.id,
            reason_code="credential_revoked",
            obligations=obligations,
            correlation_id=correlation_id,
            changed_fields=("credential", "credential_event"),
        )
        return credential


def generate_offline_manifest(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
) -> OfflineCredentialManifest:
    """Generate offline manifest.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    correlation_id : UUID
        The correlation identifier for audit tracing.

    Returns
    -------
    OfflineCredentialManifest
        The generated offline manifest.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    obligations = _require(
        actor=actor,
        capability_code="accreditation.manage_offline",
        organization_id=organization_id,
        edition_id=edition_id,
    )
    secret = settings.MARU_OFFLINE_MANIFEST_SECRET
    if not secret:
        raise ValidationError(
            "Offline manifest signing is not configured.",
            code="offline_manifest_signing_unavailable",
        )
    generated_at = timezone.now()
    with transaction.atomic():
        sequence = (
            OfflineCredentialManifest.objects.select_for_update()
            .filter(edition_id=edition_id)
            .aggregate(value=Max("sequence"))["value"]
            or 0
        ) + 1
        credentials = list(
            Credential.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                status=Credential.Status.ISSUED,
                registration__state__in=(
                    Registration.State.CONFIRMED,
                    Registration.State.CHECKED_IN,
                ),
            )
            .values("public_id", "token_digest")
            .order_by("public_id")
        )
        payload = {
            "edition_id": str(edition_id),
            "sequence": sequence,
            "valid_from": generated_at.isoformat(),
            "valid_until": (generated_at + MANIFEST_LIFETIME).isoformat(),
            "credentials": credentials,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        manifest = OfflineCredentialManifest.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            sequence=sequence,
            valid_from=generated_at,
            valid_until=generated_at + MANIFEST_LIFETIME,
            generated_at=generated_at,
            generated_by_id=actor.id,
            credential_count=len(credentials),
            payload=payload,
            payload_digest=digest,
            signature=signature,
        )
        _audit(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="accreditation.manage_offline",
            operation="accreditation.offline_manifest.generate",
            target_type="accreditation.offline_manifest",
            target_id=manifest.id,
            reason_code="offline_manifest_generated",
            obligations=obligations,
            correlation_id=correlation_id,
            changed_fields=("offline_manifest",),
        )
        return manifest


def reconcile_offline_check_in(  # noqa: PLR0915 - reconciliation keeps one atomic audit boundary
    *,
    organization_id: UUID,
    edition_id: UUID,
    device_code: str,
    operation_id: UUID,
    device_sequence: int,
    manifest_sequence: int,
    raw_credential_token: str,
    occurred_at: datetime,
    signature: str,
) -> OfflineCheckInOperation:
    """Reconcile offline check in.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    device_code : str
        The public relay-device code within the edition scope.
    operation_id : UUID
        The identifier of the operation.
    device_sequence : int
        The expected device sequence used to reject stale updates.
    manifest_sequence : int
        The expected manifest sequence used to reject stale updates.
    raw_credential_token : str
        The opaque raw credential token supplied by the caller.
    occurred_at : datetime
        The time at which the event occurred.
    signature : str
        The detached signature to authenticate before accepting the payload.

    Returns
    -------
    OfflineCheckInOperation
        The persisted result of offline check-in reconciliation.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    received_at = timezone.now()
    with transaction.atomic():
        profile = edition_adoption_profile_reference(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if profile is None or not profile_allows_offline_check_in_relay(
            profile.code,
            profile.version,
        ):
            raise ValidationError(
                "Offline check-in is unavailable for this edition profile.",
                code="offline_relay_profile_not_allowed",
            )
        device = RelayDevice.objects.select_for_update().get(
            organization_id=organization_id,
            edition_id=edition_id,
            code=device_code,
            enabled=True,
            revoked_at__isnull=True,
        )
        existing = OfflineCheckInOperation.objects.filter(
            device=device,
            operation_id=operation_id,
        ).first()
        if existing is not None:
            return existing
        secret = os.environ.get(device.signing_secret_env_var, "")
        canonical = (
            f"{operation_id}|{device_sequence}|{manifest_sequence}|"
            f"{raw_credential_token}|{occurred_at.isoformat()}"
        )
        expected = hmac.new(
            secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not secret or not hmac.compare_digest(expected, signature):
            raise ValidationError(
                "The offline operation signature is invalid.",
                code="offline_operation_signature_invalid",
            )
        if device_sequence != device.last_sequence + 1:
            raise ValidationError(
                "The offline device sequence requires reconciliation.",
                code="offline_device_sequence_conflict",
            )
        manifest = OfflineCredentialManifest.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            sequence=manifest_sequence,
        ).first()
        credential = (
            Credential.objects.select_for_update()
            .select_related("registration")
            .filter(
                organization_id=organization_id,
                edition_id=edition_id,
                token_digest=_credential_digest(raw_credential_token),
            )
            .first()
        )
        if manifest is None or not (
            manifest.valid_from <= occurred_at < manifest.valid_until
        ):
            outcome = OfflineCheckInOperation.Outcome.REJECTED
            result_code = "offline_manifest_invalid"
        elif credential is None:
            outcome = OfflineCheckInOperation.Outcome.REJECTED
            result_code = "credential_unknown"
        elif not any(
            row["token_digest"] == credential.token_digest
            for row in manifest.payload.get("credentials", [])
        ):
            outcome = OfflineCheckInOperation.Outcome.CONFLICT
            result_code = "credential_not_in_manifest"
        elif credential.status != Credential.Status.ISSUED:
            outcome = OfflineCheckInOperation.Outcome.CONFLICT
            result_code = "credential_revoked_or_replaced"
        elif credential.registration.state == Registration.State.CHECKED_IN:
            outcome = OfflineCheckInOperation.Outcome.DUPLICATE
            result_code = "already_checked_in"
        elif credential.registration.state != Registration.State.CONFIRMED:
            outcome = OfflineCheckInOperation.Outcome.CONFLICT
            result_code = "registration_not_confirmed"
        else:
            registration = Registration.objects.select_for_update().get(
                id=credential.registration_id
            )
            previous_state = registration.state
            registration.state = Registration.State.CHECKED_IN
            registration.checked_in_at = occurred_at
            registration.aggregate_version += 1
            registration.save(
                update_fields=(
                    "state",
                    "checked_in_at",
                    "aggregate_version",
                    "updated_at",
                )
            )
            CheckInRecord.objects.create(
                registration=registration,
                organization_id=organization_id,
                edition_id=edition_id,
                actor_id=device.id,
                checked_in_at=occurred_at,
                method="offline_relay",
                reason=f"Signed offline operation {operation_id}",
            )
            _append_timeline(
                registration=registration,
                kind="checked_in",
                title="Checked in",
                summary="Arrival was reconciled from an authorized offline device.",
                occurred_at=occurred_at,
                actor_kind="relay_device",
                actor_id=device.id,
                correlation_id=operation_id,
            )
            _publish_registration_transition(
                registration=registration,
                event_name="registration.checked_in.v1",
                from_state=previous_state,
                correlation_id=operation_id,
                actor_kind="relay_device",
                actor_id=device.id,
            )
            CredentialEvent.objects.create(
                credential=credential,
                organization_id=organization_id,
                edition_id=edition_id,
                kind=CredentialEvent.Kind.VERIFIED,
                occurred_at=occurred_at,
                actor_kind="relay_device",
                actor_id=device.id,
                reason_code="offline_check_in_applied",
            )
            outcome = OfflineCheckInOperation.Outcome.APPLIED
            result_code = "offline_check_in_applied"
        operation = OfflineCheckInOperation.objects.create(
            device=device,
            organization_id=organization_id,
            edition_id=edition_id,
            operation_id=operation_id,
            device_sequence=device_sequence,
            manifest_sequence=manifest_sequence,
            credential_public_id=credential.public_id if credential else "unknown",
            occurred_at=occurred_at,
            received_at=received_at,
            outcome=outcome,
            safe_result_code=result_code,
            credential=credential,
        )
        device.last_sequence = device_sequence
        device.save(update_fields=("last_sequence", "updated_at"))
        return operation
