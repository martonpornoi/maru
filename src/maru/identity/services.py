"""Application services for verified identity, sessions, and restrictions."""

from __future__ import annotations

import hashlib
import hmac
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, models, transaction
from django.http import HttpRequest
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import ResourceScope, decide
from maru.authorization.services import AuthorizationDenied
from maru.effects.services import (
    DomainEventRecord,
    enqueue_event_delivery,
    publish_domain_event,
)
from maru.identity.managers import AccountManager
from maru.identity.models import (
    Account,
    AccountRestriction,
    AccountSecurityEvent,
    AccountSession,
    IdentityAbuseBucket,
    IdentityChallenge,
    RestrictionAppeal,
)

CHALLENGE_LIFETIME: Final = timedelta(minutes=30)
RECOVERY_LIFETIME: Final = timedelta(minutes=20)
ABUSE_WINDOW: Final = timedelta(minutes=15)
ABUSE_LIMIT: Final = 8
ABUSE_BLOCK: Final = timedelta(hours=1)
STEP_UP_LIFETIME: Final = timedelta(minutes=15)
CHALLENGE_ATTEMPT_LIMIT: Final = 10


@dataclass(frozen=True, slots=True)
class ChallengeDispatch:
    """Safe result; raw_token is populated only by an explicit test setting."""

    accepted: bool
    raw_token: str | None = None


def _digest(value: str, *, purpose: str) -> str:
    key = settings.SECRET_KEY.encode()
    return hmac.new(
        key,
        f"{purpose}:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def request_fingerprint(request: HttpRequest, *, contact: str = "") -> str:
    """Key abuse controls without retaining raw addresses or network identifiers."""

    remote = request.META.get("REMOTE_ADDR", "")
    agent = request.META.get("HTTP_USER_AGENT", "")[:120]
    normalized_contact = contact.strip().casefold()
    return _digest(
        f"{remote}|{agent}|{normalized_contact}",
        purpose="identity-request",
    )


def enforce_abuse_limit(*, flow: str, subject_digest: str) -> None:
    """Consume one attempt from a fixed window under a database lock."""

    now = timezone.now()
    window_seconds = int(ABUSE_WINDOW.total_seconds())
    epoch = int(now.timestamp())
    window_started_at = now - timedelta(seconds=epoch % window_seconds)
    window_started_at = window_started_at.replace(microsecond=0)
    newly_blocked = False
    with transaction.atomic():
        try:
            bucket, _ = IdentityAbuseBucket.objects.select_for_update().get_or_create(
                flow=flow,
                subject_digest=subject_digest,
                window_started_at=window_started_at,
            )
        except IntegrityError:
            bucket = IdentityAbuseBucket.objects.select_for_update().get(
                flow=flow,
                subject_digest=subject_digest,
                window_started_at=window_started_at,
            )
        if bucket.blocked_until and bucket.blocked_until > now:
            raise ValidationError(
                "Please wait before trying again.",
                code="identity_rate_limited",
            )
        bucket.attempt_count += 1
        if bucket.attempt_count > ABUSE_LIMIT:
            bucket.blocked_until = now + ABUSE_BLOCK
        bucket.save(update_fields=("attempt_count", "blocked_until", "updated_at"))
        newly_blocked = bool(bucket.blocked_until and bucket.blocked_until > now)
    if newly_blocked:
        raise ValidationError(
            "Please wait before trying again.",
            code="identity_rate_limited",
        )


def _append_security_event(
    *,
    account: Account,
    event_type: str,
    detail_code: str,
    source_channel: str,
) -> None:
    AccountSecurityEvent.objects.create(
        account=account,
        event_type=event_type,
        outcome=AccountSecurityEvent.Outcome.SUCCEEDED,
        occurred_at=timezone.now(),
        source_channel=source_channel,
        detail_code=detail_code,
    )


def _dispatch_challenge_email(
    *,
    account: Account,
    purpose: str,
    raw_token: str,
) -> None:
    if purpose == IdentityChallenge.Purpose.VERIFY_EMAIL:
        subject = "Verify your Maru email"
        route = "verify-email"
        explanation = "verify your email before registration can reserve a place"
    else:
        subject = "Recover your Maru account"
        route = "recover-account"
        explanation = "choose a new password"
    public_base_url = settings.MARU_PUBLIC_BASE_URL.rstrip("/")
    link = f"{public_base_url}/accounts/{route}/?token={raw_token}"
    send_mail(
        subject,
        (
            f"Use this single-use link within 30 minutes to {explanation}:\n\n"
            f"{link}\n\nIf you did not request this, you can ignore this message."
        ),
        settings.DEFAULT_FROM_EMAIL,
        [account.email],
        fail_silently=False,
    )


def _raw_challenge_token(*, challenge_id: UUID, purpose: str) -> str:
    proof = _digest(str(challenge_id), purpose=f"identity-token:{purpose}")
    return f"{challenge_id.hex}.{proof}"


def deliver_identity_challenge(challenge_id: UUID) -> str:
    """Attempt one durable delivery without losing the issued challenge."""

    with transaction.atomic():
        challenge = (
            IdentityChallenge.objects.select_for_update()
            .select_related("account")
            .get(id=challenge_id)
        )
        now = timezone.now()
        if challenge.delivery_status in (
            IdentityChallenge.DeliveryStatus.SUCCEEDED,
            IdentityChallenge.DeliveryStatus.PERMANENT_FAILED,
        ):
            return challenge.delivery_status
        if (
            challenge.delivery_status == IdentityChallenge.DeliveryStatus.PROCESSING
            and challenge.last_delivery_attempt_at
            and challenge.last_delivery_attempt_at > now - timedelta(minutes=5)
        ):
            return challenge.delivery_status
        if challenge.expires_at <= now or challenge.consumed_at:
            return challenge.delivery_status
        challenge.delivery_attempt_count += 1
        challenge.last_delivery_attempt_at = now
        challenge.delivery_status = IdentityChallenge.DeliveryStatus.PROCESSING
        challenge.save(
            update_fields=(
                "delivery_attempt_count",
                "last_delivery_attempt_at",
                "delivery_status",
                "updated_at",
            )
        )
        raw_token = _raw_challenge_token(
            challenge_id=challenge.id,
            purpose=challenge.purpose,
        )
    try:
        _dispatch_challenge_email(
            account=challenge.account,
            purpose=challenge.purpose,
            raw_token=raw_token,
        )
    except smtplib.SMTPRecipientsRefused:
        status = IdentityChallenge.DeliveryStatus.PERMANENT_FAILED
        error_code = "email_recipient_rejected"
    except (OSError, smtplib.SMTPException):
        status = IdentityChallenge.DeliveryStatus.PENDING
        error_code = "email_provider_unavailable"
    else:
        status = IdentityChallenge.DeliveryStatus.SUCCEEDED
        error_code = ""
    with transaction.atomic():
        challenge = IdentityChallenge.objects.select_for_update().get(id=challenge_id)
        challenge.delivery_status = status
        challenge.delivery_error_code = error_code
        challenge.delivered_at = (
            timezone.now()
            if status == IdentityChallenge.DeliveryStatus.SUCCEEDED
            else None
        )
        challenge.save(
            update_fields=(
                "delivery_status",
                "delivery_error_code",
                "delivered_at",
                "updated_at",
            )
        )
    return status


def deliver_pending_identity_challenges(*, limit: int = 100) -> tuple[int, int]:
    """Retry unexpired identity mail; return attempted and still-pending counts."""

    now = timezone.now()
    challenge_ids = list(
        IdentityChallenge.objects.filter(
            models.Q(delivery_status=IdentityChallenge.DeliveryStatus.PENDING)
            | models.Q(
                delivery_status=IdentityChallenge.DeliveryStatus.PROCESSING,
                last_delivery_attempt_at__lte=now - timedelta(minutes=5),
            ),
            consumed_at__isnull=True,
            expires_at__gt=now,
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    pending = 0
    for challenge_id in challenge_ids:
        pending += int(
            deliver_identity_challenge(challenge_id)
            in (
                IdentityChallenge.DeliveryStatus.PENDING,
                IdentityChallenge.DeliveryStatus.PROCESSING,
            )
        )
    return len(challenge_ids), pending


def issue_identity_challenge(
    *,
    account: Account,
    purpose: str,
    fingerprint: str,
    source_channel: str,
) -> ChallengeDispatch:
    enforce_abuse_limit(flow=purpose, subject_digest=fingerprint)
    challenge_id = uuid4()
    raw_token = _raw_challenge_token(
        challenge_id=challenge_id,
        purpose=purpose,
    )
    expires_at = timezone.now() + (
        RECOVERY_LIFETIME
        if purpose == IdentityChallenge.Purpose.RECOVER_ACCOUNT
        else CHALLENGE_LIFETIME
    )
    with transaction.atomic():
        challenge = IdentityChallenge.objects.create(
            id=challenge_id,
            account=account,
            purpose=purpose,
            token_digest=_digest(raw_token, purpose="identity-challenge"),
            email_snapshot=account.email,
            expires_at=expires_at,
            request_fingerprint=fingerprint,
        )
        if purpose == IdentityChallenge.Purpose.RECOVER_ACCOUNT:
            _append_security_event(
                account=account,
                event_type=AccountSecurityEvent.EventType.RECOVERY_REQUESTED,
                detail_code="recovery_email_queued",
                source_channel=source_channel,
            )
        transaction.on_commit(lambda: deliver_identity_challenge(challenge.id))
    return ChallengeDispatch(
        accepted=True,
        raw_token=(
            raw_token
            if getattr(settings, "IDENTITY_EXPOSE_TEST_TOKENS", False)
            else None
        ),
    )


def bootstrap_account(
    *,
    email: str,
    display_name: str,
    password: str,
    fingerprint: str,
    source_channel: str = "public_api",
) -> tuple[Account | None, ChallengeDispatch]:
    """Create an unverified account without exposing whether a contact exists."""

    normalized_email = AccountManager.normalize_login_email(email)
    enforce_abuse_limit(flow="account_bootstrap", subject_digest=fingerprint)
    password_validation.validate_password(password)
    try:
        with transaction.atomic():
            account = Account.objects.create_user(
                email=normalized_email,
                display_name=display_name.strip(),
                password=password,
            )
    except (IntegrityError, ValidationError):
        existing_account = Account.objects.filter(
            email__iexact=normalized_email
        ).first()
        if existing_account is None:
            raise
        if existing_account.has_verified_email:
            return None, ChallengeDispatch(accepted=True)
        account = existing_account
    dispatch = issue_identity_challenge(
        account=account,
        purpose=IdentityChallenge.Purpose.VERIFY_EMAIL,
        fingerprint=fingerprint,
        source_channel=source_channel,
    )
    return account, dispatch


def request_account_recovery(
    *,
    email: str,
    fingerprint: str,
    source_channel: str = "public_api",
) -> ChallengeDispatch:
    """Always return the same accepted result to resist account enumeration."""

    enforce_abuse_limit(flow="account_recovery", subject_digest=fingerprint)
    account = Account.objects.filter(email__iexact=email.strip()).first()
    if account is None or not account.is_active:
        return ChallengeDispatch(accepted=True)
    return issue_identity_challenge(
        account=account,
        purpose=IdentityChallenge.Purpose.RECOVER_ACCOUNT,
        fingerprint=fingerprint,
        source_channel=source_channel,
    )


def consume_identity_challenge(
    *,
    raw_token: str,
    purpose: str,
    new_password: str = "",
    source_channel: str = "public_api",
) -> Account:
    token_digest = _digest(raw_token, purpose="identity-challenge")
    now = timezone.now()
    with transaction.atomic():
        challenge = (
            IdentityChallenge.objects.select_for_update()
            .select_related("account")
            .filter(token_digest=token_digest, purpose=purpose)
            .first()
        )
        if challenge is None:
            raise ValidationError(
                "This link is invalid or has expired.",
                code="identity_challenge_invalid",
            )
        if challenge.consumed_at or challenge.expires_at <= now:
            raise ValidationError(
                "This link is invalid or has expired.",
                code="identity_challenge_invalid",
            )
        if challenge.attempt_count >= CHALLENGE_ATTEMPT_LIMIT:
            raise ValidationError(
                "This link is invalid or has expired.",
                code="identity_challenge_invalid",
            )
        challenge.attempt_count += 1
        account = challenge.account
        if purpose == IdentityChallenge.Purpose.VERIFY_EMAIL:
            account.email_verified_at = now
            account.save(update_fields=("email_verified_at",))
            event_type = AccountSecurityEvent.EventType.CONTACT_VERIFIED
            detail_code = "email_verified"
        else:
            password_validation.validate_password(new_password, user=account)
            account.set_password(new_password)
            account.save(update_fields=("password",))
            revoke_all_sessions(
                account=account,
                reason="credential_recovery",
                exclude_session_id=None,
            )
            event_type = AccountSecurityEvent.EventType.RECOVERY_COMPLETED
            detail_code = "password_recovered"
        challenge.consumed_at = now
        challenge.save(update_fields=("attempt_count", "consumed_at", "updated_at"))
        _append_security_event(
            account=account,
            event_type=event_type,
            detail_code=detail_code,
            source_channel=source_channel,
        )
        return account


def session_key_digest(session_key: str) -> str:
    return _digest(session_key, purpose="account-session")


def inventory_session(
    *,
    account: Account,
    request: HttpRequest,
    source_channel: str = "web",
) -> AccountSession | None:
    if request.session.session_key is None:
        request.session.save()
    key = request.session.session_key
    if key is None:
        return None
    session = Session.objects.filter(session_key=key).first()
    if session is None:
        return None
    agent = request.META.get("HTTP_USER_AGENT", "").strip()
    label = agent[:120] or "Unidentified browser"
    item, _ = AccountSession.objects.update_or_create(
        session_key_digest=session_key_digest(key),
        defaults={
            "account": account,
            "session": session,
            "label": label,
            "created_channel": source_channel,
            "last_seen_at": timezone.now(),
            "revoked_at": None,
            "revocation_reason": "",
        },
    )
    return item


def revoke_session(
    *,
    account: Account,
    session_id: UUID,
    reason: str = "user_requested",
) -> AccountSession:
    with transaction.atomic():
        item = AccountSession.objects.select_for_update().get(
            id=session_id,
            account=account,
        )
        if item.revoked_at is None:
            if item.session_id:
                Session.objects.filter(session_key=item.session_id).delete()
            item.session = None
            item.revoked_at = timezone.now()
            item.revocation_reason = reason
            item.save(
                update_fields=(
                    "session",
                    "revoked_at",
                    "revocation_reason",
                    "updated_at",
                )
            )
            _append_security_event(
                account=account,
                event_type=AccountSecurityEvent.EventType.SESSION_REVOKED,
                detail_code=reason,
                source_channel="self_service",
            )
        return item


@transaction.atomic
def revoke_all_sessions(
    *,
    account: Account,
    reason: str,
    exclude_session_id: UUID | None,
) -> int:
    items = list(
        AccountSession.objects.select_for_update().filter(
            account=account,
            revoked_at__isnull=True,
        )
    )
    count = 0
    for item in items:
        if exclude_session_id and item.id == exclude_session_id:
            continue
        if item.session_id:
            Session.objects.filter(session_key=item.session_id).delete()
        item.session = None
        item.revoked_at = timezone.now()
        item.revocation_reason = reason
        item.save(
            update_fields=(
                "session",
                "revoked_at",
                "revocation_reason",
                "updated_at",
            )
        )
        count += 1
    return count


def complete_step_up(
    *,
    account: Account,
    request: HttpRequest,
    password: str,
) -> AccountSession:
    if not account.check_password(password):
        raise ValidationError(
            "The extra sign-in check failed.",
            code="step_up_failed",
        )
    item = inventory_session(account=account, request=request)
    if item is None:
        raise ValidationError(
            "The current session cannot be verified.",
            code="session_not_inventoryable",
        )
    item.step_up_verified_at = timezone.now()
    item.save(update_fields=("step_up_verified_at", "updated_at"))
    _append_security_event(
        account=account,
        event_type=AccountSecurityEvent.EventType.STEP_UP_COMPLETED,
        detail_code="password_reauthenticated",
        source_channel="self_service",
    )
    return item


def require_recent_step_up(*, account: Account, request: HttpRequest) -> None:
    key = request.session.session_key
    if not key:
        raise ValidationError(
            "Complete an extra sign-in check before this action.",
            code="step_up_required",
        )
    cutoff = timezone.now() - STEP_UP_LIFETIME
    if not AccountSession.objects.filter(
        account=account,
        session_key_digest=session_key_digest(key),
        revoked_at__isnull=True,
        step_up_verified_at__gte=cutoff,
    ).exists():
        raise ValidationError(
            "Complete an extra sign-in check before this action.",
            code="step_up_required",
        )


def active_restrictions(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    kind: str,
) -> models.QuerySet[AccountRestriction]:
    now = timezone.now()
    scope = AccountRestriction.objects.filter(
        account=account,
        organization_id=organization_id,
        kind=kind,
        status=AccountRestriction.Status.ACTIVE,
        effective_at__lte=now,
    ).filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))
    if edition_id is None:
        return scope.filter(edition__isnull=True)
    return scope.filter(
        models.Q(edition__isnull=True) | models.Q(edition_id=edition_id)
    )


def enforce_not_restricted(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    kind: str,
) -> None:
    restriction = active_restrictions(
        account=account,
        organization_id=organization_id,
        edition_id=edition_id,
        kind=kind,
    ).first()
    if restriction is not None:
        raise ValidationError(
            restriction.attendee_message
            or "This action is unavailable for this account.",
            code="account_restricted",
        )


def submit_restriction_appeal(
    *,
    account: Account,
    restriction_id: UUID,
    statement: str,
) -> RestrictionAppeal:
    restriction = AccountRestriction.objects.get(
        id=restriction_id,
        account=account,
    )
    normalized = statement.strip()
    if not normalized:
        raise ValidationError(
            {"statement": "Explain what you would like reviewed."},
            code="appeal_statement_required",
        )
    return RestrictionAppeal.objects.create(
        restriction=restriction,
        account=account,
        statement=normalized,
        submitted_at=timezone.now(),
    )


def _require_restriction_authority(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
) -> tuple[str, ...]:
    decision = decide(
        principal=actor,
        capability_code="identity.manage_restrictions",
        resource=ResourceScope(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "Restriction management is unavailable.",
            reason_code=decision.reason_code,
        )
    return tuple(sorted(decision.obligations))


def issue_account_restriction(
    *,
    actor: Account,
    account: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    kind: str,
    reason_code: str,
    attendee_message: str,
    internal_reference: str,
    effective_at: object,
    expires_at: object | None,
    notify_account: bool,
    correlation_id: UUID,
) -> AccountRestriction:
    obligations = _require_restriction_authority(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if kind not in AccountRestriction.Kind.values:
        raise ValidationError(
            "Choose a supported restriction kind.",
            code="restriction_kind_invalid",
        )
    if not reason_code.strip() or not attendee_message.strip():
        raise ValidationError(
            "Restrictions require a safe reason code and attendee message.",
            code="restriction_reason_required",
        )
    if not isinstance(effective_at, datetime) or (
        expires_at is not None and not isinstance(expires_at, datetime)
    ):
        raise ValidationError(
            "Restriction dates are invalid.",
            code="restriction_date_invalid",
        )
    with transaction.atomic():
        restriction = AccountRestriction.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
            kind=kind,
            reason_code=reason_code,
            attendee_message=attendee_message,
            internal_reference=internal_reference,
            effective_at=effective_at,
            expires_at=expires_at,
            issued_by=actor,
            notify_account=notify_account,
        )
        if effective_at <= timezone.now():
            from maru.registration.restrictions import (  # noqa: PLC0415
                apply_restriction_consequences,
            )

            apply_restriction_consequences(restriction=restriction, actor=actor)
            restriction.consequences_applied_at = timezone.now()
            restriction.save(update_fields=("consequences_applied_at", "updated_at"))
            _publish_restriction_applied(
                restriction=restriction,
                correlation_id=correlation_id,
                actor_kind="account",
                actor_id=actor.id,
            )
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor.id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="identity.manage_restrictions",
                operation="identity.restriction.issue",
                target_type="identity.account_restriction",
                target_id=restriction.id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="restriction_issued",
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
                obligations=obligations,
                changed_fields=("restriction", "registration_consequences"),
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="security-extended",
            )
        )
        return restriction


def _publish_restriction_applied(
    *,
    restriction: AccountRestriction,
    correlation_id: UUID,
    actor_kind: str,
    actor_id: UUID | None,
) -> None:
    event, _ = publish_domain_event(
        DomainEventRecord(
            event_name="identity.account_restriction.applied.v1",
            schema_version=1,
            organization_id=restriction.organization_id,
            event_edition_id=restriction.edition_id,
            aggregate_type="identity.account_restriction",
            aggregate_id=restriction.id,
            aggregate_version=1,
            payload={
                "restriction_kind": restriction.kind,
                "status": restriction.status,
            },
            correlation_id=correlation_id,
            causation_id=None,
            actor_kind=actor_kind,
            actor_id=actor_id,
            retention_class="security-extended",
        ),
        workload_pool="security",
    )
    if restriction.notify_account:
        enqueue_event_delivery(
            event=event,
            destination="notifications",
            workload_pool="notifications",
        )


def apply_due_account_restrictions(
    *,
    edition_id: UUID | None = None,
    now: datetime | None = None,
) -> int:
    """Apply effective scheduled restrictions exactly once."""

    effective_at = now or timezone.now()
    applied = 0
    scope = AccountRestriction.objects.filter(
        status=AccountRestriction.Status.ACTIVE,
        consequences_applied_at__isnull=True,
        effective_at__lte=effective_at,
    ).filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=effective_at))
    if edition_id is not None:
        scope = scope.filter(edition_id=edition_id)
    with transaction.atomic():
        restrictions = list(
            scope.select_for_update(skip_locked=True)
            .select_related("issued_by")
            .order_by("effective_at", "id")
        )
        for restriction in restrictions:
            from maru.registration.restrictions import (  # noqa: PLC0415
                apply_restriction_consequences,
            )

            apply_restriction_consequences(
                restriction=restriction,
                actor=restriction.issued_by,
            )
            restriction.consequences_applied_at = effective_at
            restriction.save(update_fields=("consequences_applied_at", "updated_at"))
            _publish_restriction_applied(
                restriction=restriction,
                correlation_id=restriction.id,
                actor_kind="system",
                actor_id=None,
            )
            applied += 1
    return applied


def revoke_account_restriction(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    restriction_id: UUID,
    reason: str,
    correlation_id: UUID,
) -> AccountRestriction:
    obligations = _require_restriction_authority(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    normalized = reason.strip()
    if not normalized:
        raise ValidationError(
            "Revocation requires a reason.",
            code="restriction_revocation_reason_required",
        )
    with transaction.atomic():
        restriction = AccountRestriction.objects.select_for_update().get(
            id=restriction_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if restriction.status == AccountRestriction.Status.REVOKED:
            return restriction
        restriction.status = AccountRestriction.Status.REVOKED
        restriction.revoked_at = timezone.now()
        restriction.revoked_by = actor
        restriction.revocation_reason = normalized
        restriction.save(
            update_fields=(
                "status",
                "revoked_at",
                "revoked_by",
                "revocation_reason",
                "updated_at",
            )
        )
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor.id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="identity.manage_restrictions",
                operation="identity.restriction.revoke",
                target_type="identity.account_restriction",
                target_id=restriction.id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="restriction_revoked",
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
                obligations=obligations,
                changed_fields=("restriction",),
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="security-extended",
            )
        )
        return restriction


def decide_restriction_appeal(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    appeal_id: UUID,
    decision: str,
    summary: str,
    correlation_id: UUID,
) -> RestrictionAppeal:
    obligations = _require_restriction_authority(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    normalized_summary = summary.strip()
    if not normalized_summary:
        raise ValidationError(
            "Appeal decisions require a safe attendee-facing summary.",
            code="appeal_decision_summary_required",
        )
    if decision not in {"uphold", "revoke"}:
        raise ValidationError(
            "Choose a supported appeal decision.",
            code="appeal_decision_invalid",
        )
    decided_at = timezone.now()
    with transaction.atomic():
        appeal = (
            RestrictionAppeal.objects.select_for_update()
            .select_related("restriction")
            .get(
                id=appeal_id,
                restriction__organization_id=organization_id,
                restriction__edition_id=edition_id,
            )
        )
        if appeal.status != RestrictionAppeal.Status.OPEN:
            raise ValidationError(
                "This appeal was already decided.",
                code="appeal_already_decided",
            )
        appeal.status = (
            RestrictionAppeal.Status.UPHELD
            if decision == "uphold"
            else RestrictionAppeal.Status.RESOLVED
        )
        appeal.decided_at = decided_at
        appeal.decided_by = actor
        appeal.decision_summary = normalized_summary
        appeal.full_clean()
        appeal.save(
            update_fields=(
                "status",
                "decided_at",
                "decided_by",
                "decision_summary",
                "updated_at",
            )
        )
        if decision == "revoke":
            revoke_account_restriction(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                restriction_id=appeal.restriction_id,
                reason=normalized_summary,
                correlation_id=correlation_id,
            )
        else:
            append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=actor.id,
                    principal_context_id=None,
                    organization_id=organization_id,
                    event_edition_id=edition_id,
                    capability_code="identity.manage_restrictions",
                    operation="identity.restriction_appeal.uphold",
                    target_type="identity.restriction_appeal",
                    target_id=appeal.id,
                    outcome=AuditEvent.Outcome.ALLOW,
                    reason_code="restriction_appeal_upheld",
                    correlation_id=correlation_id,
                    request_id=correlation_id,
                    source_channel="api",
                    obligations=obligations,
                    changed_fields=("appeal",),
                    safe_metadata={"policy_version": POLICY_VERSION},
                    retention_class="security-extended",
                )
            )
        return appeal
