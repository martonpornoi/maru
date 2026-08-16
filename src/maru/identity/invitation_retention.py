"""Approved, bounded retention for abandoned platform invitation identities.

The retention duration is deployment policy, never a code-owned legal answer.
This module fails closed unless one complete, reviewed policy is configured.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.identity.invitation_inputs import validate_source_channel
from maru.identity.models import (
    Account,
    AccountSecurityEvent,
    IdentityChallenge,
    PlatformAccountInventoryControl,
    PlatformAccountInvitation,
    PlatformIdentityDelivery,
    PlatformIdentityDeliveryAttempt,
    PlatformIdentityDeliveryLateOutcome,
    PlatformInvitationRetentionAssessment,
    PlatformInvitationRetentionHold,
    PlatformInvitationRetentionPolicyControl,
    PlatformInvitationRetentionReceipt,
    PlatformInvitationSchedulerRun,
)

RETENTION_POLICY_SETTING: Final = "MARU_IDENTITY_INVITATION_RETENTION_POLICY_JSON"
RETENTION_POLICY_TRIGGER: Final = "terminal_transition"
RETENTION_POLICY_ACTION: Final = "anonymize_abandoned_invitation_contact"
RETENTION_RUN_GENERATION: Final = "retention-v2"
MAX_RETENTION_BATCH: Final = 100
RETENTION_TOMBSTONE_CHUNK: Final = 128
MAX_POLICY_BYTES: Final = 4_096
MAX_RETENTION_DAYS: Final = 36_500
MAX_POLICY_APPROVED_AT_LENGTH: Final = 64
MAX_POLICY_VERSION: Final = 2_147_483_647
RETENTION_RESULT_CODE: Final = "abandoned_invitation_contact_anonymized"

_POLICY_KEYS: Final = frozenset(
    {
        "policy_id",
        "version",
        "jurisdiction_code",
        "trigger",
        "period_days",
        "action",
        "approved_by_reference",
        "approved_at",
    }
)
_POLICY_CODE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,119}$")
_JURISDICTION_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,39}$")
_TOMBSTONE_EMAIL = re.compile(
    r"^disposed-[0-9a-f]{32}@account\.invalid$",
    flags=re.ASCII,
)
_PROVIDER_TOMBSTONE = re.compile(
    r"^disposed-provider-[0-9a-f]{32}$",
    flags=re.ASCII,
)
_RETENTION_SOURCE_CHANNELS: Final = frozenset({"operator", "scheduler"})
_RETENTION_ADVISORY_LOCK_KEY: Final = int.from_bytes(b"MARURET8", "big")
_ALLOWED_SECURITY_EVENT_TYPES: Final = frozenset(
    {
        AccountSecurityEvent.EventType.ACCOUNT_INVITATION_CREATED,
        AccountSecurityEvent.EventType.ACCOUNT_INVITATION_REISSUED,
        AccountSecurityEvent.EventType.ACCOUNT_INVITATION_REVOKED,
        AccountSecurityEvent.EventType.ACCOUNT_INVITATION_EXPIRED,
    }
)
_ALLOWED_ACCOUNT_RELATIONS: Final = frozenset(
    {
        ("identity.AccountSecurityEvent", "account"),
        ("identity.IdentityChallenge", "account"),
        ("identity.PlatformAccountInvitation", "account"),
    }
)


class InvitationRetentionConfigurationError(RuntimeError):
    """The deployment has no complete approved invitation retention policy."""


class InvitationRetentionUnavailableError(RuntimeError):
    """The selected invitation cannot safely enter the disposal workflow."""


@dataclass(frozen=True, slots=True)
class InvitationRetentionPolicy:
    policy_id: str
    version: int
    jurisdiction_code: str
    trigger: Literal["terminal_transition"]
    period_days: int
    action: Literal["anonymize_abandoned_invitation_contact"]
    approved_by_reference: str
    approved_at: datetime
    digest: str

    def due_at(self, trigger_at: datetime) -> datetime:
        return trigger_at + timedelta(days=self.period_days)


@dataclass(frozen=True, slots=True)
class InvitationRetentionRunResult:
    disposed_count: int
    held_count: int
    blocked_count: int
    remaining_count: int
    heartbeat_id: UUID


def _policy_error() -> InvitationRetentionConfigurationError:
    return InvitationRetentionConfigurationError(
        "Configure one complete, independently approved platform invitation "
        "retention policy before running disposal."
    )


def _closed_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous duplicate JSON members before policy normalization."""

    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate invitation retention policy member")
        document[key] = value
    return document


def _retention_source_channel(value: object) -> str:
    """Use the shared syntax contract plus this workflow's exact allowlist."""

    channel = validate_source_channel(value)
    if channel not in _RETENTION_SOURCE_CHANNELS:
        raise ValidationError(
            {"source_channel": "Choose an approved retention source channel."},
            code="invitation_retention_source_channel_invalid",
        )
    return channel


def _database_now() -> datetime:
    """Use the database server as the authority for persisted evidence time."""

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_catalog.clock_timestamp()")
        row = cursor.fetchone()
    if row is None or not isinstance(row[0], datetime):
        raise InvitationRetentionUnavailableError
    return row[0]


def _normalized_approved_at(value: object) -> datetime:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_POLICY_APPROVED_AT_LENGTH
    ):
        raise _policy_error()
    parsed = parse_datetime(value)
    if parsed is None or timezone.is_naive(parsed):
        raise _policy_error()
    normalized = parsed.astimezone(UTC)
    try:
        database_now = _database_now().astimezone(UTC)
    except (DatabaseError, InvitationRetentionUnavailableError) as error:
        raise _policy_error() from error
    if normalized > database_now:
        raise _policy_error()
    return normalized


def configured_invitation_retention_policy() -> InvitationRetentionPolicy:
    """Return the strict deployment policy or fail without a fallback period."""

    raw = getattr(settings, RETENTION_POLICY_SETTING, "")
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw.encode("utf-8")) > MAX_POLICY_BYTES
    ):
        raise _policy_error()
    try:
        document = json.loads(raw, object_pairs_hook=_closed_json_object)
    except (TypeError, ValueError) as error:
        raise _policy_error() from error
    if not isinstance(document, dict) or set(document) != _POLICY_KEYS:
        raise _policy_error()

    policy_id = document["policy_id"]
    version = document["version"]
    jurisdiction_code = document["jurisdiction_code"]
    trigger = document["trigger"]
    period_days = document["period_days"]
    action = document["action"]
    approved_by_reference = document["approved_by_reference"]
    approved_at = _normalized_approved_at(document["approved_at"])
    if (
        not isinstance(policy_id, str)
        or _POLICY_CODE.fullmatch(policy_id) is None
        or type(version) is not int
        or not 1 <= version <= MAX_POLICY_VERSION
        or not isinstance(jurisdiction_code, str)
        or _JURISDICTION_CODE.fullmatch(jurisdiction_code) is None
        or trigger != RETENTION_POLICY_TRIGGER
        or type(period_days) is not int
        or not 0 <= period_days <= MAX_RETENTION_DAYS
        or action != RETENTION_POLICY_ACTION
        or not isinstance(approved_by_reference, str)
        or _POLICY_CODE.fullmatch(approved_by_reference) is None
    ):
        raise _policy_error()

    normalized = {
        "action": action,
        "approved_at": approved_at.isoformat().replace("+00:00", "Z"),
        "approved_by_reference": approved_by_reference,
        "jurisdiction_code": jurisdiction_code,
        "period_days": period_days,
        "policy_id": policy_id,
        "trigger": trigger,
        "version": version,
    }
    digest = hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return InvitationRetentionPolicy(
        policy_id=policy_id,
        version=version,
        jurisdiction_code=jurisdiction_code,
        trigger=RETENTION_POLICY_TRIGGER,
        period_days=period_days,
        action=RETENTION_POLICY_ACTION,
        approved_by_reference=approved_by_reference,
        approved_at=approved_at,
        digest=digest,
    )


def invitation_retention_policy_is_ready() -> bool:
    try:
        configured_invitation_retention_policy()
    except InvitationRetentionConfigurationError:
        return False
    return True


def _policy_control_values(policy: InvitationRetentionPolicy) -> dict[str, object]:
    return {
        "generation": "retention-policy-v1",
        "policy_id": policy.policy_id,
        "policy_version": policy.version,
        "policy_digest": policy.digest,
        "jurisdiction_code": policy.jurisdiction_code,
        "policy_approved_by_reference": policy.approved_by_reference,
        "policy_approved_at": policy.approved_at,
        "trigger": policy.trigger,
        "retention_period_days": policy.period_days,
        "action": policy.action,
    }


def invitation_retention_policy_control_is_ready() -> bool:
    """Require the owner-activated database control to equal the environment."""

    try:
        policy = configured_invitation_retention_policy()
        control = (
            PlatformInvitationRetentionPolicyControl.objects.filter(singleton=True)
            .values(*_policy_control_values(policy).keys())
            .first()
        )
    except (DatabaseError, InvitationRetentionConfigurationError):
        return False
    return bool(control == _policy_control_values(policy))


def activate_configured_invitation_retention_policy() -> (
    PlatformInvitationRetentionPolicyControl
):
    """Pin reviewed environment policy in the migration-owner control plane."""

    policy = configured_invitation_retention_policy()
    values = _policy_control_values(policy)
    # The activation instant is evidence, not caller input.  Materialize it
    # from PostgreSQL once so neither an application clock nor a maintenance
    # caller can backdate the control plane.
    activated_at = _database_now()
    with transaction.atomic():
        control = (
            PlatformInvitationRetentionPolicyControl.objects.select_for_update()
            .filter(singleton=True)
            .first()
        )
        if control is None:
            return PlatformInvitationRetentionPolicyControl.objects.create(
                singleton=True,
                activated_at=activated_at,
                **values,
            )
        current = {key: getattr(control, key) for key in values}
        if current == values:
            return control
        if policy.version <= control.policy_version:
            raise InvitationRetentionConfigurationError(
                "A retention policy change must advance its positive version."
            )
        for key, value in values.items():
            setattr(control, key, value)
        control.activated_at = activated_at
        control.save(update_fields=(*values.keys(), "activated_at"))
        return control


def _normalize_policy_code(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(
            {field: "Use a stable lowercase policy code."},
            code="invitation_retention_code_invalid",
        )
    normalized = value.strip().lower()
    if _POLICY_CODE.fullmatch(normalized) is None:
        raise ValidationError(
            {field: "Use a stable lowercase policy code."},
            code="invitation_retention_code_invalid",
        )
    return normalized


def _lock_platform_actor(actor: Account) -> Account:
    persisted = Account.objects.select_for_update().filter(id=actor.id).first()
    if (
        persisted is None
        or not persisted.is_active
        or not persisted.is_platform_administrator
    ):
        raise ValidationError(
            "An active platform administrator is required.",
            code="invitation_retention_actor_invalid",
        )
    return persisted


def _append_retention_audit(
    *,
    actor: Account | None,
    operation: str,
    target_type: str,
    target_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    changed_fields: tuple[str, ...],
    policy: InvitationRetentionPolicy | None = None,
    occurred_at: datetime,
) -> None:
    safe_metadata: dict[str, object] = {"contract_version": "page10-v1"}
    if policy is not None:
        safe_metadata.update(
            {
                "policy_version": f"{policy.policy_id}:v{policy.version}",
                "policy_digest": policy.digest,
            }
        )
    append_audit(
        AuditRecord(
            principal_kind="account" if actor is not None else "system",
            principal_id=actor.id if actor is not None else None,
            principal_context_id=None,
            organization_id=None,
            event_edition_id=None,
            capability_code="identity.manage_account_invitations",
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="approved_retention_policy",
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("audit_privileged_mutation",),
            changed_fields=changed_fields,
            safe_metadata=safe_metadata,
            retention_class="identity-restricted",
        ),
        occurred_at=occurred_at,
    )


def place_invitation_retention_hold(
    *,
    actor: Account,
    invitation_id: UUID,
    reference_code: object,
    reason_code: object,
    correlation_id: UUID,
    source_channel: object = "operator",
) -> PlatformInvitationRetentionHold:
    """Place one current legal/security hold through an audited service."""

    channel = _retention_source_channel(source_channel)
    reference = _normalize_policy_code(reference_code, field="reference_code")
    reason = _normalize_policy_code(reason_code, field="reason_code")
    with transaction.atomic():
        locked_actor = _lock_platform_actor(actor)
        invitation = (
            PlatformAccountInvitation.objects.select_for_update()
            .filter(id=invitation_id)
            .first()
        )
        if invitation is None or hasattr(invitation, "retention_receipt"):
            raise InvitationRetentionUnavailableError
        current = (
            PlatformInvitationRetentionHold.objects.select_for_update()
            .filter(invitation=invitation, active=True)
            .first()
        )
        if current is not None:
            if (
                current.placed_by_id == locked_actor.id
                and current.reference_code == reference
                and current.reason_code == reason
                and current.place_correlation_id == correlation_id
            ):
                return current
            raise ValidationError(
                "This invitation already has an active retention hold.",
                code="invitation_retention_hold_exists",
            )
        occurred_at = _database_now()
        hold_id = uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH evidence AS MATERIALIZED (
                    SELECT clock_timestamp() AS recorded_at
                )
                INSERT INTO identity_platforminvitationretentionhold (
                    id, created_at, updated_at, invitation_id,
                    reference_code, reason_code, placed_at, placed_by_id,
                    place_correlation_id, active, released_at, released_by_id,
                    release_reason_code, release_correlation_id
                )
                SELECT %s, evidence.recorded_at, evidence.recorded_at, %s,
                    %s, %s, %s, %s, %s, true, NULL, NULL, '', NULL
                  FROM evidence
                """,
                [
                    hold_id,
                    invitation.id,
                    reference,
                    reason,
                    occurred_at,
                    locked_actor.id,
                    correlation_id,
                ],
            )
        hold = PlatformInvitationRetentionHold.objects.get(id=hold_id)
        _append_retention_audit(
            actor=locked_actor,
            operation="identity.account_invitation.retention_hold.place",
            target_type="identity.platform_invitation_retention_hold",
            target_id=hold.id,
            correlation_id=correlation_id,
            source_channel=channel,
            changed_fields=("active",),
            occurred_at=occurred_at,
        )
        return hold


def release_invitation_retention_hold(
    *,
    actor: Account,
    hold_id: UUID,
    reason_code: object,
    correlation_id: UUID,
    source_channel: object = "operator",
) -> PlatformInvitationRetentionHold:
    """Release a hold once; the placed and released evidence remains."""

    channel = _retention_source_channel(source_channel)
    reason = _normalize_policy_code(reason_code, field="reason_code")
    with transaction.atomic():
        locked_actor = _lock_platform_actor(actor)
        hold = (
            PlatformInvitationRetentionHold.objects.select_for_update()
            .select_related("invitation")
            .filter(id=hold_id)
            .first()
        )
        if hold is None:
            raise InvitationRetentionUnavailableError
        if not hold.active:
            if (
                hold.released_by_id == locked_actor.id
                and hold.release_reason_code == reason
                and hold.release_correlation_id == correlation_id
            ):
                return hold
            raise ValidationError(
                "This retention hold was already released.",
                code="invitation_retention_hold_released",
            )
        occurred_at = _database_now()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE identity_platforminvitationretentionhold
                   SET active = false,
                       released_at = %s,
                       released_by_id = %s,
                       release_reason_code = %s,
                       release_correlation_id = %s,
                       updated_at = clock_timestamp()
                 WHERE id = %s
                """,
                [
                    occurred_at,
                    locked_actor.id,
                    reason,
                    correlation_id,
                    hold.id,
                ],
            )
        hold.refresh_from_db()
        _append_retention_audit(
            actor=locked_actor,
            operation="identity.account_invitation.retention_hold.release",
            target_type="identity.platform_invitation_retention_hold",
            target_id=hold.id,
            correlation_id=correlation_id,
            source_channel=channel,
            changed_fields=("active", "released_at"),
            occurred_at=occurred_at,
        )
        return hold


def _terminal_trigger_at(invitation: PlatformAccountInvitation) -> datetime | None:
    if invitation.status == PlatformAccountInvitation.Status.REVOKED:
        return invitation.revoked_at
    if invitation.status == PlatformAccountInvitation.Status.EXPIRED:
        return invitation.expired_at
    return None


def _has_other_account_relationship(account: Account) -> bool:
    """Fail closed on every current or future non-invitation account relation."""

    if account.groups.exists() or account.user_permissions.exists():
        return True
    for relation in Account._meta.related_objects:
        related_model = relation.related_model
        if not isinstance(related_model, type):
            return True
        relation_identity = (
            related_model._meta.label,
            relation.field.name,
        )
        if relation_identity in _ALLOWED_ACCOUNT_RELATIONS:
            continue
        lookup = {relation.field.name: account.id}
        if related_model._base_manager.filter(**lookup).exists():
            return True
    return False


def _account_disposition_blocker(
    *,
    account: Account,
    invitation: PlatformAccountInvitation,
) -> str | None:
    if (
        account.account_kind != Account.Kind.PERSON
        or account.is_active
        or account.is_staff
        or account.is_superuser
        or account.email_verified_at is not None
        or account.has_usable_password()
        or account.last_login is not None
        or account.invitation_provisioning_origin_id != invitation.id
    ):
        return PlatformInvitationRetentionAssessment.ResultCode.ACCOUNT_STATE
    if (
        AccountSecurityEvent.objects.filter(account=account)
        .exclude(event_type__in=_ALLOWED_SECURITY_EVENT_TYPES)
        .exists()
    ):
        return PlatformInvitationRetentionAssessment.ResultCode.SECURITY_HISTORY
    if (
        IdentityChallenge.objects.filter(account=account)
        .exclude(
            purpose=IdentityChallenge.Purpose.ACCOUNT_INVITATION,
            invitation=invitation,
        )
        .exists()
    ):
        return PlatformInvitationRetentionAssessment.ResultCode.CHALLENGE_RELATIONSHIP
    if _has_other_account_relationship(account):
        return PlatformInvitationRetentionAssessment.ResultCode.ACCOUNT_RELATIONSHIP
    return None


def _due_candidates(
    *,
    policy: InvitationRetentionPolicy,
    at: datetime,
) -> QuerySet[PlatformAccountInvitation]:
    cutoff = at - timedelta(days=policy.period_days)
    return (
        PlatformAccountInvitation.objects.filter(
            status__in=(
                PlatformAccountInvitation.Status.REVOKED,
                PlatformAccountInvitation.Status.EXPIRED,
            ),
            last_transition_at__lte=cutoff,
        )
        .filter(retention_receipt__isnull=True)
        .order_by("last_transition_at", "id")
    )


def _unheld_due_candidates(
    *,
    policy: InvitationRetentionPolicy,
    at: datetime,
) -> QuerySet[PlatformAccountInvitation]:
    """Return only actionable due work for the production backlog signal."""

    return _due_candidates(policy=policy, at=at).exclude(retention_holds__active=True)


def _tombstone_material() -> tuple[bytes, str]:
    key = secrets.token_bytes(32)
    contact_digest = hmac.new(key, b"account-contact", hashlib.sha256).hexdigest()
    return key, f"disposed-{contact_digest[:32]}@account.invalid"


def _challenge_tombstone(key: bytes, challenge: IdentityChallenge) -> tuple[str, str]:
    token_digest = hmac.new(
        key,
        b"challenge-token:" + challenge.id.bytes,
        hashlib.sha256,
    ).hexdigest()
    fingerprint = hmac.new(
        key,
        b"request-fingerprint:" + challenge.id.bytes,
        hashlib.sha256,
    ).hexdigest()
    return token_digest, fingerprint


def _provider_tombstone(key: bytes, delivery_id: UUID) -> str:
    digest = hmac.new(
        key,
        b"provider-reference:" + delivery_id.bytes,
        hashlib.sha256,
    ).hexdigest()
    tombstone = f"disposed-provider-{digest[:32]}"
    if _PROVIDER_TOMBSTONE.fullmatch(tombstone) is None:
        raise InvitationRetentionUnavailableError
    return tombstone


def _record_retention_assessment(
    *,
    invitation: PlatformAccountInvitation,
    policy: InvitationRetentionPolicy,
    safe_result_code: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH evidence AS MATERIALIZED (
                SELECT clock_timestamp() AS recorded_at
            )
            INSERT INTO identity_platforminvitationretentionassessment (
                id, created_at, updated_at, invitation_id, policy_digest,
                terminal_version, assessment_version, safe_result_code,
                assessed_at
            )
            SELECT %s, evidence.recorded_at, evidence.recorded_at, %s, %s,
                   %s, 1, %s, evidence.recorded_at
              FROM evidence
            ON CONFLICT (invitation_id) DO UPDATE
               SET policy_digest = EXCLUDED.policy_digest,
                   terminal_version = EXCLUDED.terminal_version,
                   assessment_version =
                       identity_platforminvitationretentionassessment.assessment_version
                       + 1,
                   safe_result_code = EXCLUDED.safe_result_code,
                   assessed_at = EXCLUDED.assessed_at,
                   updated_at = EXCLUDED.updated_at
            """,
            [
                uuid4(),
                invitation.id,
                policy.digest,
                invitation.aggregate_version,
                safe_result_code,
            ],
        )


def _tombstone_invitation_challenges(
    *,
    invitation: PlatformAccountInvitation,
    account: Account,
    disposal_key: bytes,
    tombstone_email: str,
    at: datetime,
) -> None:
    """Tombstone arbitrary legitimate history with bounded in-memory keysets."""

    last_id: UUID | None = None
    while True:
        chunk_query = IdentityChallenge.objects.select_for_update().filter(
            account=account,
            invitation=invitation,
            purpose=IdentityChallenge.Purpose.ACCOUNT_INVITATION,
        )
        if last_id is not None:
            chunk_query = chunk_query.filter(id__gt=last_id)
        challenges = list(chunk_query.order_by("id")[:RETENTION_TOMBSTONE_CHUNK])
        if not challenges:
            return
        for challenge in challenges:
            token_digest, request_fingerprint = _challenge_tombstone(
                disposal_key,
                challenge,
            )
            challenge.email_snapshot = tombstone_email
            challenge.token_digest = token_digest
            challenge.token_digest_key_id = ""
            challenge.request_fingerprint = request_fingerprint
            challenge.updated_at = at
        IdentityChallenge.objects.bulk_update(
            challenges,
            (
                "email_snapshot",
                "token_digest",
                "token_digest_key_id",
                "request_fingerprint",
                "updated_at",
            ),
            batch_size=RETENTION_TOMBSTONE_CHUNK,
        )
        last_id = challenges[-1].id


def _tombstone_provider_references(
    *,
    invitation: PlatformAccountInvitation,
    disposal_key: bytes,
    at: datetime,
) -> None:
    """Replace raw provider material across the complete delivery evidence graph."""

    last_id: UUID | None = None
    while True:
        delivery_query = PlatformIdentityDelivery.objects.select_for_update().filter(
            invitation=invitation
        )
        if last_id is not None:
            delivery_query = delivery_query.filter(id__gt=last_id)
        deliveries = list(delivery_query.order_by("id")[:RETENTION_TOMBSTONE_CHUNK])
        if not deliveries:
            return
        for delivery in deliveries:
            tombstone = _provider_tombstone(disposal_key, delivery.id)
            if delivery.provider_reference:
                PlatformIdentityDelivery.objects.filter(id=delivery.id).update(
                    provider_reference=tombstone,
                    updated_at=at,
                )
            PlatformIdentityDeliveryAttempt.objects.filter(delivery=delivery).exclude(
                provider_reference=""
            ).update(
                provider_reference=tombstone,
                updated_at=at,
            )
            PlatformIdentityDeliveryLateOutcome.objects.filter(
                delivery=delivery
            ).exclude(provider_reference="").update(
                provider_reference=tombstone,
                updated_at=at,
            )
        last_id = deliveries[-1].id


def _dispose_one(  # noqa: PLR0911
    *,
    invitation_id: UUID,
    policy: InvitationRetentionPolicy,
    at: datetime,
    source_channel: str,
) -> Literal["disposed", "held", "blocked", "replayed"]:
    with transaction.atomic():
        invitation = (
            PlatformAccountInvitation.objects.select_for_update()
            .select_related("account")
            .filter(id=invitation_id)
            .first()
        )
        if invitation is None:
            return "replayed"
        existing = PlatformInvitationRetentionReceipt.objects.filter(
            invitation=invitation
        ).first()
        if existing is not None:
            return "replayed"
        trigger_at = _terminal_trigger_at(invitation)
        if trigger_at is None or policy.due_at(trigger_at) > at:
            _record_retention_assessment(
                invitation=invitation,
                policy=policy,
                safe_result_code=(
                    PlatformInvitationRetentionAssessment.ResultCode.NOT_DUE
                ),
            )
            return "blocked"
        account = Account.objects.select_for_update().get(id=invitation.account_id)
        if (
            PlatformInvitationRetentionHold.objects.select_for_update()
            .filter(
                invitation=invitation,
                active=True,
            )
            .exists()
        ):
            _record_retention_assessment(
                invitation=invitation,
                policy=policy,
                safe_result_code=(
                    PlatformInvitationRetentionAssessment.ResultCode.ACTIVE_HOLD
                ),
            )
            return "held"
        account_blocker = _account_disposition_blocker(
            account=account,
            invitation=invitation,
        )
        if account_blocker is not None:
            _record_retention_assessment(
                invitation=invitation,
                policy=policy,
                safe_result_code=account_blocker,
            )
            return "blocked"
        if (
            PlatformAccountInvitation.objects.filter(account=account)
            .exclude(id=invitation.id)
            .exists()
        ):
            _record_retention_assessment(
                invitation=invitation,
                policy=policy,
                safe_result_code=(
                    PlatformInvitationRetentionAssessment.ResultCode.ADDITIONAL_INVITATION
                ),
            )
            return "blocked"
        if invitation.current_challenge_id is not None:
            _record_retention_assessment(
                invitation=invitation,
                policy=policy,
                safe_result_code=(
                    PlatformInvitationRetentionAssessment.ResultCode.ACTIVE_CHALLENGE
                ),
            )
            return "blocked"
        challenges = IdentityChallenge.objects.filter(
            account=account,
            invitation=invitation,
            purpose=IdentityChallenge.Purpose.ACCOUNT_INVITATION,
        )
        if (
            not challenges.exists()
            or challenges.filter(
                Q(consumed_at__isnull=False) | Q(invalidated_at__isnull=True)
            ).exists()
        ):
            _record_retention_assessment(
                invitation=invitation,
                policy=policy,
                safe_result_code=(
                    PlatformInvitationRetentionAssessment.ResultCode.CHALLENGE_STATE
                ),
            )
            return "blocked"
        if (
            not invitation.deliveries.exists()
            or invitation.deliveries.filter(
                Q(payload_destroyed_at__isnull=True)
                | Q(status=PlatformIdentityDelivery.Status.PROCESSING)
                | Q(
                    reconciliation_state=(
                        PlatformIdentityDelivery.ReconciliationState.REQUIRED
                    )
                )
            ).exists()
        ):
            _record_retention_assessment(
                invitation=invitation,
                policy=policy,
                safe_result_code=(
                    PlatformInvitationRetentionAssessment.ResultCode.DELIVERY_UNRESOLVED
                ),
            )
            return "blocked"

        control = PlatformAccountInventoryControl.objects.select_for_update().get(
            singleton=True
        )
        correlation_id = uuid4()
        due_at = policy.due_at(trigger_at)
        receipt_id = uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH evidence AS MATERIALIZED (
                    SELECT clock_timestamp() AS recorded_at
                )
                INSERT INTO identity_platforminvitationretentionreceipt (
                    id, created_at, updated_at, inventory_control_id,
                    invitation_id, policy_id, policy_version, policy_digest,
                    jurisdiction_code, policy_approved_by_reference,
                    policy_approved_at, trigger, retention_period_days,
                    terminal_version, trigger_at, due_at, action, applied_at,
                    correlation_id, source_channel, safe_result_code
                )
                SELECT %s, evidence.recorded_at, evidence.recorded_at,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                  FROM evidence
                """,
                [
                    receipt_id,
                    control.singleton,
                    invitation.id,
                    policy.policy_id,
                    policy.version,
                    policy.digest,
                    policy.jurisdiction_code,
                    policy.approved_by_reference,
                    policy.approved_at,
                    policy.trigger,
                    policy.period_days,
                    invitation.aggregate_version,
                    trigger_at,
                    due_at,
                    policy.action,
                    at,
                    correlation_id,
                    source_channel,
                    RETENTION_RESULT_CODE,
                ],
            )
        disposal_key, tombstone_email = _tombstone_material()
        if _TOMBSTONE_EMAIL.fullmatch(tombstone_email) is None:
            raise InvitationRetentionUnavailableError
        Account.objects.filter(id=account.id).update(
            email=tombstone_email,
            login_handle="",
            display_name="",
        )
        _tombstone_invitation_challenges(
            invitation=invitation,
            account=account,
            disposal_key=disposal_key,
            tombstone_email=tombstone_email,
            at=at,
        )
        _tombstone_provider_references(
            invitation=invitation,
            disposal_key=disposal_key,
            at=at,
        )
        _append_retention_audit(
            actor=None,
            operation="identity.account_invitation.retention_apply",
            target_type="identity.platform_account_invitation",
            target_id=invitation.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=(
                "account_contact",
                "challenge_contact",
                "challenge_lookup_evidence",
                "delivery_provider_reference",
                "retention_receipt",
            ),
            policy=policy,
            occurred_at=at,
        )
        _record_retention_assessment(
            invitation=invitation,
            policy=policy,
            safe_result_code=(
                PlatformInvitationRetentionAssessment.ResultCode.DISPOSED
            ),
        )
        # Best-effort removal of this Python reference. Python process-memory
        # behavior does not provide a guaranteed secure erase; the key is never
        # persisted or returned and dies with this bounded transaction scope.
        disposal_key = b""
        del disposal_key, receipt_id
        return "disposed"


def _remaining_due_count(
    *,
    policy: InvitationRetentionPolicy,
    at: datetime,
) -> int:
    return len(
        list(
            _unheld_due_candidates(policy=policy, at=at).values_list("id", flat=True)[
                : MAX_RETENTION_BATCH + 1
            ]
        )
    )


def _candidate_page(
    *,
    policy: InvitationRetentionPolicy,
    at: datetime,
    limit: int,
) -> list[tuple[UUID, datetime]]:
    base = _due_candidates(policy=policy, at=at)
    cursor = (
        PlatformInvitationSchedulerRun.objects.filter(
            kind=PlatformInvitationSchedulerRun.Kind.RETENTION,
            generation=PlatformInvitationSchedulerRun.Generation.RETENTION_V2,
        )
        .order_by("-ran_at", "-id")
        .values_list(
            "retention_cursor_transition_at",
            "retention_cursor_invitation_id",
        )
        .first()
    )
    page = base
    has_cursor = False
    if cursor is not None and cursor[0] is not None and cursor[1] is not None:
        has_cursor = True
        cursor_at, cursor_id = cursor
        page = base.filter(
            Q(last_transition_at__gt=cursor_at)
            | Q(last_transition_at=cursor_at, id__gt=cursor_id)
        )
    candidates = list(page.values_list("id", "last_transition_at")[:limit])
    if not candidates and has_cursor:
        candidates = list(base.values_list("id", "last_transition_at")[:limit])
    return candidates


@contextmanager
def _retention_worker_lock() -> Iterator[None]:
    """Serialize only retention cursors while leaving other identity work live."""

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", [_RETENTION_ADVISORY_LOCK_KEY])
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(%s)",
                [_RETENTION_ADVISORY_LOCK_KEY],
            )


def run_platform_invitation_retention(
    *,
    limit: int = MAX_RETENTION_BATCH,
    source_channel: object = "scheduler",
) -> InvitationRetentionRunResult:
    """Dispose a bounded batch and append a policy-bound scheduler heartbeat."""

    if type(limit) is not int or not 1 <= limit <= MAX_RETENTION_BATCH:
        raise ValidationError(
            {
                "limit": (
                    f"Choose a retention batch from 1 through {MAX_RETENTION_BATCH}."
                )
            },
            code="invitation_retention_limit_invalid",
        )
    channel = _retention_source_channel(source_channel)
    policy = configured_invitation_retention_policy()
    if not invitation_retention_policy_control_is_ready():
        raise InvitationRetentionConfigurationError(
            "Activate the exact configured retention policy in the database "
            "control plane before running disposal."
        )
    # One actual PostgreSQL instant controls candidate eligibility and every
    # per-target receipt/tombstone/audit write.  There is deliberately no
    # public backdating override.
    now = _database_now()
    with _retention_worker_lock():
        candidates = _candidate_page(policy=policy, at=now, limit=limit)
        disposed_count = 0
        held_count = 0
        blocked_count = 0
        for invitation_id, _transition_at in candidates:
            try:
                outcome = _dispose_one(
                    invitation_id=invitation_id,
                    policy=policy,
                    at=now,
                    source_channel=channel,
                )
            except IntegrityError as error:
                # A uniqueness race may mean another worker completed the same target.
                if PlatformInvitationRetentionReceipt.objects.filter(
                    invitation_id=invitation_id
                ).exists():
                    outcome = "replayed"
                else:
                    raise InvitationRetentionUnavailableError from error
            if outcome == "disposed":
                disposed_count += 1
            elif outcome == "held":
                held_count += 1
            elif outcome == "blocked":
                blocked_count += 1
        heartbeat_at = _database_now()
        remaining_count = _remaining_due_count(policy=policy, at=heartbeat_at)
        if candidates:
            cursor_invitation_id, cursor_transition_at = candidates[-1]
        else:
            cursor_invitation_id = None
            cursor_transition_at = None
        heartbeat_id = uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH evidence AS MATERIALIZED (
                    SELECT clock_timestamp() AS recorded_at
                )
                INSERT INTO identity_platforminvitationschedulerrun (
                    id, created_at, updated_at, kind, generation, ran_at,
                    processed_count, remaining_count,
                    private_key_coverage_complete, policy_digest,
                    inspected_count, blocked_count, held_count,
                    retention_cursor_transition_at,
                    retention_cursor_invitation_id
                )
                SELECT %s, evidence.recorded_at, evidence.recorded_at,
                    'retention', 'retention-v2', evidence.recorded_at,
                    %s, %s, false, %s, %s, %s, %s, %s, %s
                  FROM evidence
                """,
                [
                    heartbeat_id,
                    disposed_count,
                    remaining_count,
                    policy.digest,
                    len(candidates),
                    blocked_count,
                    held_count,
                    cursor_transition_at,
                    cursor_invitation_id,
                ],
            )
        heartbeat = PlatformInvitationSchedulerRun.objects.get(id=heartbeat_id)
    return InvitationRetentionRunResult(
        disposed_count=disposed_count,
        held_count=held_count,
        blocked_count=blocked_count,
        remaining_count=remaining_count,
        heartbeat_id=heartbeat.id,
    )


def terminal_invitation_payloads_are_destroyed() -> bool:
    """Prove C4 envelopes do not survive any invitation terminal transition."""

    try:
        return not PlatformAccountInvitation.objects.filter(
            status__in=(
                PlatformAccountInvitation.Status.ACCEPTED,
                PlatformAccountInvitation.Status.REVOKED,
                PlatformAccountInvitation.Status.EXPIRED,
            ),
            deliveries__payload_destroyed_at__isnull=True,
        ).exists()
    except DatabaseError:
        return False


__all__ = [
    "InvitationRetentionConfigurationError",
    "InvitationRetentionPolicy",
    "InvitationRetentionRunResult",
    "InvitationRetentionUnavailableError",
    "activate_configured_invitation_retention_policy",
    "configured_invitation_retention_policy",
    "invitation_retention_policy_control_is_ready",
    "invitation_retention_policy_is_ready",
    "place_invitation_retention_hold",
    "release_invitation_retention_hold",
    "run_platform_invitation_retention",
    "terminal_invitation_payloads_are_destroyed",
]
