"""Authentication-facing platform account and scoped access safety records."""

import base64
import binascii
from typing import Any, ClassVar
from uuid import uuid4

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.postgres.indexes import OpClass
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower, Upper
from django.utils import timezone

from maru.core.models import UUIDTimeStampedModel
from maru.identity.managers import AccountManager

ASCII_CONTROL_LIMIT = 32
ASCII_DELETE = 127
SHA256_HEX_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-f]{64}$",
    message="Use a lowercase SHA-256 hex digest.",
    code="invalid_digest",
)
SAFE_DELIVERY_CODE_VALIDATOR = RegexValidator(
    regex=r"^[a-z0-9][a-z0-9_.-]{0,119}$",
    message="Use a stable lowercase delivery code.",
    code="invalid_delivery_code",
)
RETENTION_POLICY_CODE_VALIDATOR = RegexValidator(
    regex=r"^[a-z0-9][a-z0-9_.:-]{0,119}$",
    message="Use a stable lowercase retention-policy code.",
    code="invalid_retention_policy_code",
)
INVITATION_SOURCE_CHANNEL_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_-]{0,39}$",
    message="Use a stable lowercase source-channel code.",
    code="invalid_invitation_source_channel",
)
INVITATION_ENCRYPTION_KEY_ID_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$",
    message="Use a stable invitation encryption key identifier.",
    code="invalid_invitation_encryption_key_id",
)
INVITATION_DELIVERY_ENCRYPTION_ALGORITHM = "aes-256-gcm+rsa-oaep-sha256-v1"
INVITATION_PAYLOAD_NONCE_BYTES = 12
INVITATION_PAYLOAD_MIN_DECODED_BYTES = 17
INVITATION_PAYLOAD_MAX_DECODED_BYTES = 4_112
INVITATION_WRAPPED_KEY_MIN_DECODED_BYTES = 256
INVITATION_WRAPPED_KEY_MAX_DECODED_BYTES = 512
INVITATION_PAYLOAD_MAX_ENCODED_BYTES = 5_483
INVITATION_WRAPPED_KEY_MAX_ENCODED_BYTES = 683


def _validate_canonical_base64url(
    value: bytes | memoryview | None,
    *,
    field_name: str,
    minimum_decoded: int,
    maximum_decoded: int,
) -> None:
    """Reject malformed or non-canonical encrypted envelope components."""

    if value is None:
        return
    encoded = bytes(value)
    if not encoded or b"=" in encoded:
        raise ValidationError(
            {field_name: "Use non-empty unpadded base64url bytes."},
            code="invalid_invitation_envelope",
        )
    try:
        decoded = base64.b64decode(
            encoded + (b"=" * (-len(encoded) % 4)),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError):
        raise ValidationError(
            {field_name: "Use canonical base64url bytes."},
            code="invalid_invitation_envelope",
        ) from None
    if (
        not minimum_decoded <= len(decoded) <= maximum_decoded
        or base64.urlsafe_b64encode(decoded).rstrip(b"=") != encoded
    ):
        raise ValidationError(
            {field_name: "Use a bounded canonical base64url value."},
            code="invalid_invitation_envelope",
        )


class PlatformAccountInventoryControl(models.Model):
    """The single optimistic-concurrency boundary for platform account reads."""

    singleton = models.BooleanField(primary_key=True, default=True, editable=False)
    aggregate_version = models.PositiveBigIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(singleton=True),
                name="identity_account_inventory_singleton",
            )
        ]

    def __str__(self) -> str:
        return f"Platform account inventory v{self.aggregate_version}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.singleton = True
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "The account inventory control is retained for recovery.",
            code="protected_account_inventory_control",
        )


def validate_login_handle(value: str) -> None:
    """Keep human aliases printable while preserving public roster spelling."""

    if "@" in value:
        raise ValidationError(
            "A login username cannot contain @; use an email address instead.",
            code="login_handle_email_ambiguity",
        )
    if any(character.isspace() and character not in {" "} for character in value):
        raise ValidationError(
            "A login username cannot contain control whitespace.",
            code="login_handle_control_whitespace",
        )
    if any(
        ord(character) < ASCII_CONTROL_LIMIT or ord(character) == ASCII_DELETE
        for character in value
    ):
        raise ValidationError(
            "A login username cannot contain control characters.",
            code="login_handle_control_character",
        )


class Account(AbstractBaseUser, PermissionsMixin):
    """One platform login, separate from organizer-owned person records."""

    class Kind(models.TextChoices):
        PERSON = "person", "Person"
        PLATFORM_ADMINISTRATOR = (
            "platform_administrator",
            "Platform administrator",
        )

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    email = models.EmailField(unique=True)
    login_handle = models.CharField(
        max_length=120,
        blank=True,
        validators=(validate_login_handle,),
        help_text=(
            "Optional human sign-in name. It is unique without regard to letter case."
        ),
    )
    display_name = models.CharField(max_length=120, blank=True)
    preferred_language = models.CharField(max_length=35, default="en")
    account_kind = models.CharField(
        max_length=32,
        choices=Kind,
        default=Kind.PERSON,
    )
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now, editable=False)
    invitation_provisioning_origin = models.OneToOneField(
        "PlatformAccountInvitation",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="provisioned_account",
        help_text=(
            "Exact platform invitation that originally reserved this identity; "
            "blank for accounts created through another approved identity flow."
        ),
    )

    objects = AccountManager()

    EMAIL_FIELD = "email"
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        ordering = ("date_joined", "id")
        indexes = [
            models.Index(
                fields=("date_joined", "id"),
                name="identity_account_joined_idx",
            ),
            models.Index(
                OpClass(Upper("email"), name="varchar_pattern_ops"),
                name="id_account_email_prefix_idx",
            ),
            models.Index(
                OpClass(Upper("login_handle"), name="varchar_pattern_ops"),
                name="id_account_handle_prefix_idx",
            ),
            models.Index(
                OpClass(Upper("display_name"), name="varchar_pattern_ops"),
                name="id_account_name_prefix_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="account_email_case_insensitive_unique",
            ),
            models.UniqueConstraint(
                Lower("login_handle"),
                condition=~models.Q(login_handle=""),
                name="account_login_handle_case_insensitive_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(email=""),
                name="account_email_not_empty",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(account_kind="platform_administrator")
                    | (models.Q(is_staff=True) & models.Q(is_superuser=True))
                ),
                name="account_platform_admin_has_privileges",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_superuser=False)
                    | models.Q(account_kind="platform_administrator")
                ),
                name="account_superuser_is_platform_admin",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = AccountManager.normalize_login_email(self.email)
        self.login_handle = self.login_handle.strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.display_name or self.login_handle or str(self.id)

    @property
    def has_verified_email(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_platform_administrator(self) -> bool:
        """Identify platform operators without implying convention participation."""

        return self.account_kind == self.Kind.PLATFORM_ADMINISTRATOR


NAVIGATION_DESTINATION_CODE_VALIDATOR = RegexValidator(
    regex=r"^[a-z0-9][a-z0-9._-]{0,159}$",
    message="Use a stable lowercase navigation destination code.",
    code="invalid_navigation_destination_code",
)


class NavigationPin(UUIDTimeStampedModel):
    """One personal shortcut that never grants access to its destination."""

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="navigation_pins",
    )
    destination_code = models.CharField(
        max_length=160,
        validators=(NAVIGATION_DESTINATION_CODE_VALIDATOR,),
    )

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("account", "destination_code"),
                name="identity_navigation_pin_account_destination_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    destination_code__regex=r"^[a-z0-9][a-z0-9._-]{0,159}$"
                ),
                name="identity_navigation_pin_destination_code_valid",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.destination_code


class AccountSecurityEvent(UUIDTimeStampedModel):
    """A minimized, subject-visible account security projection."""

    class EventType(models.TextChoices):
        SIGN_IN = "sign_in", "Signed in"
        SIGN_OUT = "sign_out", "Signed out"
        CREDENTIAL_CHANGED = "credential_changed", "Credential changed"
        CONTACT_VERIFIED = "contact_verified", "Contact verified"
        RECOVERY_REQUESTED = "recovery_requested", "Recovery requested"
        RECOVERY_COMPLETED = "recovery_completed", "Recovery completed"
        SESSION_REVOKED = "session_revoked", "Session revoked"
        STEP_UP_COMPLETED = "step_up_completed", "Extra sign-in check completed"
        DATA_EXPORT = "data_export", "Account export"
        ACCOUNT_INVITATION_CREATED = (
            "account_invitation_created",
            "Account invitation created",
        )
        ACCOUNT_INVITATION_REISSUED = (
            "account_invitation_reissued",
            "Account invitation reissued",
        )
        ACCOUNT_INVITATION_REVOKED = (
            "account_invitation_revoked",
            "Account invitation revoked",
        )
        ACCOUNT_INVITATION_EXPIRED = (
            "account_invitation_expired",
            "Account invitation expired",
        )
        ACCOUNT_INVITATION_ACCEPTED = (
            "account_invitation_accepted",
            "Account invitation accepted",
        )

    class Outcome(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="security_events",
    )
    event_type = models.CharField(max_length=40, choices=EventType)
    outcome = models.CharField(max_length=20, choices=Outcome)
    occurred_at = models.DateTimeField()
    source_channel = models.CharField(max_length=40)
    detail_code = models.CharField(max_length=80)

    class Meta:
        ordering = ("-occurred_at", "-id")
        indexes = [
            models.Index(
                fields=("account", "occurred_at"),
                name="identity_sec_acct_time_idx",
            )
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValueError("Account security history is append-only.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValueError("Account security history is append-only.")

    def __str__(self) -> str:
        return f"{self.account}: {self.get_event_type_display()}"


class IdentityChallenge(UUIDTimeStampedModel):
    """One single-use, hashed email verification or recovery challenge."""

    class Purpose(models.TextChoices):
        VERIFY_EMAIL = "verify_email", "Verify email"
        RECOVER_ACCOUNT = "recover_account", "Recover account"
        ACCOUNT_INVITATION = "account_invitation", "Accept account invitation"

    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        PERMANENT_FAILED = "permanent_failed", "Permanent failure"
        SUPPRESSED = "suppressed", "Managed by identity delivery"

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="identity_challenges",
    )
    purpose = models.CharField(max_length=24, choices=Purpose)
    token_digest = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        validators=(SHA256_HEX_VALIDATOR,),
    )
    token_digest_key_id = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        validators=(INVITATION_ENCRYPTION_KEY_ID_VALIDATOR,),
        help_text=(
            "Versioned HMAC key used for invitation-token lookup. Blank values "
            "are retained only on terminal challenges created before key rotation."
        ),
    )
    email_snapshot = models.EmailField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    invalidation_reason = models.CharField(max_length=80, blank=True)
    invitation = models.ForeignKey(
        "PlatformAccountInvitation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="identity_challenges",
    )
    invitation_version = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        editable=False,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    request_fingerprint = models.CharField(
        max_length=64,
        editable=False,
        validators=(SHA256_HEX_VALIDATOR,),
    )
    delivery_status = models.CharField(
        max_length=24,
        choices=DeliveryStatus,
        default=DeliveryStatus.PENDING,
    )
    delivery_attempt_count = models.PositiveSmallIntegerField(default=0)
    last_delivery_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_error_code = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("account", "purpose", "expires_at"),
                name="identity_challenge_lookup_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(attempt_count__lte=10),
                name="identity_challenge_attempt_limit",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        purpose="account_invitation",
                        invitation__isnull=False,
                        invitation_version__gt=0,
                    )
                    | (
                        ~models.Q(purpose="account_invitation")
                        & models.Q(
                            invitation__isnull=True,
                            invitation_version__isnull=True,
                        )
                    )
                ),
                name="identity_challenge_invitation_lineage",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        invalidated_at__isnull=True,
                        invalidation_reason="",
                    )
                    | (
                        models.Q(invalidated_at__isnull=False)
                        & ~models.Q(invalidation_reason="")
                    )
                ),
                name="identity_challenge_invalidation_evidence",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(consumed_at__isnull=True)
                    | models.Q(invalidated_at__isnull=True)
                ),
                name="identity_challenge_not_consumed_invalidated",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    token_digest__regex=r"^[0-9a-f]{64}$"  # noqa: S106
                ),
                name="identity_challenge_token_digest_canonical",
            ),
            models.CheckConstraint(
                condition=models.Q(request_fingerprint__regex=r"^[0-9a-f]{64}$"),
                name="identity_challenge_fingerprint_canonical",
            ),
            models.UniqueConstraint(
                fields=("invitation",),
                condition=models.Q(
                    purpose="account_invitation",
                    consumed_at__isnull=True,
                    invalidated_at__isnull=True,
                ),
                name="identity_one_active_challenge_per_invite",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        purpose="account_invitation",
                        delivery_status="suppressed",
                        delivery_attempt_count=0,
                        last_delivery_attempt_at__isnull=True,
                        delivered_at__isnull=True,
                        delivery_error_code="",
                    )
                    | ~models.Q(purpose="account_invitation")
                ),
                name="identity_invitation_legacy_delivery_suppressed",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        is_invitation = self.purpose == self.Purpose.ACCOUNT_INVITATION
        if is_invitation:
            is_terminal = (
                self.consumed_at is not None or self.invalidated_at is not None
            )
            if not self.token_digest_key_id and not is_terminal:
                raise ValidationError(
                    {
                        "token_digest_key_id": ValidationError(
                            (
                                "An active invitation challenge requires a "
                                "versioned digest key."
                            ),
                            code="identity_challenge_digest_key_required",
                        )
                    },
                )
        elif self.token_digest_key_id:
            raise ValidationError(
                {
                    "token_digest_key_id": ValidationError(
                        (
                            "Only account-invitation challenges use invitation "
                            "digest keys."
                        ),
                        code="identity_challenge_digest_key_not_allowed",
                    )
                },
            )
        if self.email_snapshot.casefold() != self.account.email.casefold():
            raise ValidationError(
                "The challenge contact does not match the account.",
                code="identity_challenge_contact_mismatch",
            )
        if is_invitation and self.invitation_id:
            invitation = self.invitation
            if invitation is None or invitation.account_id != self.account_id:
                raise ValidationError(
                    "The challenge invitation must reserve the same account.",
                    code="identity_challenge_invitation_account_mismatch",
                )
            if (
                self.invitation_version is not None
                and self.invitation_version > invitation.aggregate_version
            ):
                raise ValidationError(
                    {"invitation_version": "The challenge version is not current."},
                    code="identity_challenge_invitation_version_invalid",
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email_snapshot = self.email_snapshot.strip().lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Identity challenges expire through the retention workflow.",
            code="protected_identity_challenge",
        )


class PlatformAccountInvitation(UUIDTimeStampedModel):
    """Versioned platform invitation that never grants convention authority."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="platform_account_invitations",
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    expires_at = models.DateTimeField()
    last_transition_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    current_challenge = models.OneToOneField(
        IdentityChallenge,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for_platform_invitation",
    )
    created_by = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="platform_account_invitations_created",
    )

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("status", "expires_at", "id"),
                name="id_invite_status_expiry_idx",
            ),
            models.Index(
                fields=("status", "last_transition_at", "id"),
                name="id_inv_retention_due_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gt=0),
                name="identity_invitation_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="pending",
                        accepted_at__isnull=True,
                        revoked_at__isnull=True,
                        expired_at__isnull=True,
                    )
                    | models.Q(
                        status="accepted",
                        accepted_at__isnull=False,
                        revoked_at__isnull=True,
                        expired_at__isnull=True,
                    )
                    | models.Q(
                        status="revoked",
                        accepted_at__isnull=True,
                        revoked_at__isnull=False,
                        expired_at__isnull=True,
                    )
                    | models.Q(
                        status="expired",
                        accepted_at__isnull=True,
                        revoked_at__isnull=True,
                        expired_at__isnull=False,
                    )
                ),
                name="identity_invitation_status_timestamp",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="pending")
                    | models.Q(current_challenge__isnull=True)
                ),
                name="identity_terminal_invitation_no_current",
            ),
            models.UniqueConstraint(
                fields=("account",),
                condition=models.Q(status="pending"),
                name="identity_one_pending_invite_per_account",
            ),
            models.UniqueConstraint(
                fields=("account",),
                name="identity_one_invitation_per_account",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.account_id:
            account = self.account
            if (
                account.account_kind != Account.Kind.PERSON
                or account.is_staff
                or account.is_superuser
            ):
                raise ValidationError(
                    "An invitation may reserve only a non-privileged person account.",
                    code="invitation_subject_kind_invalid",
                )
            if self.status != self.Status.ACCEPTED and (
                account.is_active
                or account.email_verified_at is not None
                or account.has_usable_password()
            ):
                raise ValidationError(
                    "An unaccepted invitation requires an inactive reserved identity.",
                    code="invitation_subject_state_invalid",
                )
            # Acceptance is historical evidence. A later legitimate account
            # deactivation, address lifecycle, or credential reset must not make
            # the completed invitation graph invalid retroactively.
        if self.created_by_id and not self.created_by.is_platform_administrator:
            raise ValidationError(
                "Invitation creator provenance must identify a platform administrator.",
                code="invitation_creator_invalid",
            )
        if self.current_challenge_id:
            challenge = self.current_challenge
            if (
                challenge is None
                or challenge.purpose != IdentityChallenge.Purpose.ACCOUNT_INVITATION
                or challenge.account_id != self.account_id
                or challenge.invitation_id != self.id
                or challenge.invitation_version != self.aggregate_version
                or challenge.consumed_at is not None
                or challenge.invalidated_at is not None
            ):
                raise ValidationError(
                    {"current_challenge": "Select the exact active current challenge."},
                    code="invitation_current_challenge_invalid",
                )
        if self.accepted_at and self.accepted_at > self.expires_at:
            raise ValidationError(
                {"accepted_at": "An invitation cannot be accepted after expiry."},
                code="invitation_acceptance_after_expiry",
            )
        if self.expired_at and self.expired_at < self.expires_at:
            raise ValidationError(
                {"expired_at": "Expiry evidence cannot predate the deadline."},
                code="invitation_expiry_before_deadline",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Account invitations require the identity retention workflow.",
            code="protected_platform_account_invitation",
        )


class PlatformAccountInvitationTransition(UUIDTimeStampedModel):
    """Append-only invitation lifecycle and reason evidence."""

    class Operation(models.TextChoices):
        CREATED = "created", "Created"
        REISSUED = "reissued", "Reissued"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"
        ACCEPTED = "accepted", "Accepted"

    invitation = models.ForeignKey(
        PlatformAccountInvitation,
        on_delete=models.PROTECT,
        related_name="transitions",
    )
    version = models.PositiveBigIntegerField()
    operation = models.CharField(max_length=16, choices=Operation)
    actor = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="platform_account_invitation_transitions_acted",
    )
    occurred_at = models.DateTimeField()
    reason = models.CharField(max_length=240)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(
        max_length=40,
        validators=(INVITATION_SOURCE_CHANNEL_VALIDATOR,),
    )

    class Meta:
        ordering = ("invitation_id", "version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("invitation", "version"),
                name="identity_invitation_transition_version_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="identity_invitation_transition_version_positive",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="identity_invitation_transition_reason_nonempty",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if not self.reason.strip():
            raise ValidationError(
                {"reason": "A lifecycle transition requires a reason."},
                code="invitation_transition_reason_required",
            )
        if self.invitation_id and self.version > self.invitation.aggregate_version:
            raise ValidationError(
                {"version": "The transition cannot exceed the aggregate version."},
                code="invitation_transition_version_invalid",
            )
        if self.operation != self.Operation.EXPIRED and self.actor_id is None:
            raise ValidationError(
                {"actor": "This invitation transition requires an actor."},
                code="invitation_transition_actor_required",
            )
        actor = self.actor
        if self.actor_id and (actor is None or not actor.is_active):
            raise ValidationError(
                {"actor": "The transition actor must be active."},
                code="invitation_transition_actor_inactive",
            )
        if self.actor_id and self.operation == self.Operation.ACCEPTED:
            if self.actor_id != self.invitation.account_id:
                raise ValidationError(
                    {"actor": "Only the reserved account may accept its invitation."},
                    code="invitation_acceptance_actor_mismatch",
                )
        elif self.actor_id and (actor is None or not actor.is_platform_administrator):
            raise ValidationError(
                {"actor": "Administrative transitions require a platform operator."},
                code="invitation_transition_actor_invalid",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Invitation transitions are append-only.",
                code="immutable_invitation_transition",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Invitation transitions are append-only.",
            code="immutable_invitation_transition",
        )


class PlatformAccountInvitationCommandReceipt(UUIDTimeStampedModel):
    """Scope-bound append-only idempotency evidence for invitation commands."""

    class Operation(models.TextChoices):
        CREATE = "create", "Create"
        REISSUE = "reissue", "Reissue"
        REVOKE = "revoke", "Revoke"
        ACCEPT = "accept", "Accept"

    inventory_control = models.ForeignKey(
        PlatformAccountInventoryControl,
        default=True,
        on_delete=models.PROTECT,
        related_name="invitation_command_receipts",
    )
    invitation = models.ForeignKey(
        PlatformAccountInvitation,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    actor = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="platform_account_invitation_command_receipts",
    )
    operation = models.CharField(max_length=16, choices=Operation)
    retry_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=(SHA256_HEX_VALIDATOR,),
    )
    expected_version = models.PositiveBigIntegerField()
    result_version = models.PositiveBigIntegerField()
    correlation_id = models.UUIDField()
    source_channel = models.CharField(
        max_length=40,
        validators=(INVITATION_SOURCE_CHANNEL_VALIDATOR,),
    )

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("inventory_control", "actor", "retry_key"),
                name="identity_invitation_retry_scope_unique",
            ),
            models.UniqueConstraint(
                fields=("invitation", "result_version"),
                name="identity_invitation_result_receipt_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                name="identity_invitation_request_digest_canonical",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        operation="create",
                        expected_version=0,
                        result_version=1,
                    )
                    | (
                        models.Q(
                            operation__in=("reissue", "revoke", "accept"),
                            expected_version__gt=0,
                        )
                        & models.Q(result_version=models.F("expected_version") + 1)
                    )
                ),
                name="identity_invitation_receipt_version_consistent",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.inventory_control_id is not True:
            raise ValidationError(
                {"inventory_control": "Use the platform account inventory scope."},
                code="invitation_receipt_scope_invalid",
            )
        if (
            self.invitation_id
            and self.result_version > self.invitation.aggregate_version
        ):
            raise ValidationError(
                {"result_version": "The result version is not present."},
                code="invitation_receipt_result_version_invalid",
            )
        if self.actor_id and not self.actor.is_active:
            raise ValidationError(
                {"actor": "The command actor must be active."},
                code="invitation_command_actor_inactive",
            )
        if self.actor_id and self.operation == self.Operation.ACCEPT:
            if self.actor_id != self.invitation.account_id:
                raise ValidationError(
                    {"actor": "Only the reserved account may accept its invitation."},
                    code="invitation_acceptance_actor_mismatch",
                )
        elif self.actor_id and not self.actor.is_platform_administrator:
            raise ValidationError(
                {"actor": "Invitation commands require a platform operator."},
                code="invitation_command_actor_invalid",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Invitation command receipts are append-only.",
                code="immutable_invitation_command_receipt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Invitation command receipts are append-only.",
            code="immutable_invitation_command_receipt",
        )


class PlatformIdentityDelivery(UUIDTimeStampedModel):
    """Durable platform-global delivery state for one invitation challenge."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DELIVERED = "delivered", "Delivered"
        RETRYING = "retrying", "Retrying"
        PERMANENT_FAILED = "permanent_failed", "Permanent failure"
        CANCELLED = "cancelled", "Cancelled"

    class ReconciliationState(models.TextChoices):
        NOT_REQUIRED = "not_required", "Not required"
        REQUIRED = "required", "Required"
        RESOLVED = "resolved", "Resolved"

    class PayloadDestructionReason(models.TextChoices):
        DELIVERED = "delivered", "Delivered"
        REVOKED = "revoked", "Invitation revoked"
        SUPERSEDED = "superseded", "Challenge superseded"
        EXPIRED = "expired", "Invitation expired"

    invitation = models.ForeignKey(
        PlatformAccountInvitation,
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    challenge = models.OneToOneField(
        IdentityChallenge,
        on_delete=models.PROTECT,
        related_name="platform_identity_delivery",
    )
    status = models.CharField(max_length=24, choices=Status, default=Status.PENDING)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    available_at = models.DateTimeField(default=timezone.now)
    provider_idempotency_key = models.UUIDField(
        default=uuid4,
        unique=True,
        editable=False,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=8)
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    provider_reference = models.CharField(max_length=160, blank=True)
    safe_error_code = models.CharField(
        max_length=120,
        blank=True,
        validators=(SAFE_DELIVERY_CODE_VALIDATOR,),
    )
    reconciliation_state = models.CharField(
        max_length=20,
        choices=ReconciliationState,
        default=ReconciliationState.NOT_REQUIRED,
    )
    reconciliation_required_at = models.DateTimeField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciliation_code = models.CharField(
        max_length=120,
        blank=True,
        validators=(SAFE_DELIVERY_CODE_VALIDATOR,),
    )
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    cancellation_code = models.CharField(
        max_length=120,
        blank=True,
        validators=(SAFE_DELIVERY_CODE_VALIDATOR,),
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    encryption_algorithm = models.CharField(max_length=64, blank=True)
    encryption_key_id = models.CharField(
        max_length=64,
        blank=True,
        validators=(INVITATION_ENCRYPTION_KEY_ID_VALIDATOR,),
    )
    encrypted_payload = models.BinaryField(
        max_length=INVITATION_PAYLOAD_MAX_ENCODED_BYTES,
        null=True,
        blank=True,
        editable=False,
    )
    wrapped_data_key = models.BinaryField(
        max_length=INVITATION_WRAPPED_KEY_MAX_ENCODED_BYTES,
        null=True,
        blank=True,
        editable=False,
    )
    payload_nonce = models.BinaryField(
        max_length=INVITATION_PAYLOAD_NONCE_BYTES,
        null=True,
        blank=True,
        editable=False,
    )
    payload_aad_digest = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        validators=(SHA256_HEX_VALIDATOR,),
    )
    payload_destroyed_at = models.DateTimeField(null=True, blank=True)
    payload_destruction_reason = models.CharField(
        max_length=16,
        choices=PayloadDestructionReason,
        blank=True,
    )

    class Meta:
        ordering = ("available_at", "created_at", "id")
        indexes = [
            models.Index(
                fields=("status", "available_at", "id"),
                name="identity_delivery_claim_idx",
            ),
            models.Index(
                fields=("status", "lease_expires_at", "id"),
                name="identity_delivery_lease_idx",
            ),
            models.Index(
                fields=("reconciliation_state", "created_at", "id"),
                name="id_delivery_reconcile_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gt=0),
                name="identity_delivery_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(max_attempts__gte=1, max_attempts__lte=100)
                    & models.Q(attempt_count__lte=models.F("max_attempts"))
                ),
                name="identity_delivery_attempt_bounds",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="processing",
                        claimed_at__isnull=False,
                        lease_expires_at__isnull=False,
                        lease_token__isnull=False,
                    )
                    | (
                        ~models.Q(status="processing")
                        & models.Q(
                            claimed_at__isnull=True,
                            lease_expires_at__isnull=True,
                            lease_token__isnull=True,
                        )
                    )
                ),
                name="identity_delivery_lease_matches_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="retrying", next_retry_at__isnull=False)
                    | (
                        ~models.Q(status="retrying")
                        & models.Q(next_retry_at__isnull=True)
                    )
                ),
                name="identity_delivery_retry_matches_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="delivered", delivered_at__isnull=False)
                    | (
                        ~models.Q(status="delivered")
                        & models.Q(delivered_at__isnull=True)
                    )
                ),
                name="identity_delivery_success_matches_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=("retrying", "permanent_failed", "cancelled"),
                    )
                    & ~models.Q(safe_error_code="")
                    | (
                        models.Q(status__in=("pending", "processing", "delivered"))
                        & models.Q(safe_error_code="")
                    )
                ),
                name="identity_delivery_error_matches_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(attempt_count=0, last_attempt_at__isnull=True)
                    | (
                        models.Q(attempt_count__gt=0)
                        & models.Q(last_attempt_at__isnull=False)
                    )
                ),
                name="identity_delivery_attempt_timestamp",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        reconciliation_state="not_required",
                        reconciliation_required_at__isnull=True,
                        reconciled_at__isnull=True,
                        reconciliation_code="",
                    )
                    | models.Q(
                        reconciliation_state="required",
                        reconciliation_required_at__isnull=False,
                        reconciled_at__isnull=True,
                        reconciliation_code="",
                    )
                    | (
                        models.Q(
                            reconciliation_state="resolved",
                            reconciliation_required_at__isnull=False,
                            reconciled_at__isnull=False,
                        )
                        & ~models.Q(reconciliation_code="")
                    )
                ),
                name="identity_delivery_reconciliation_evidence",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        cancellation_requested_at__isnull=True,
                        cancellation_code="",
                        cancelled_at__isnull=True,
                    )
                    | (
                        models.Q(
                            cancellation_requested_at__isnull=False,
                            status__in=("processing", "cancelled"),
                            payload_destroyed_at__isnull=False,
                        )
                        & ~models.Q(cancellation_code="")
                    )
                ),
                name="identity_delivery_cancellation_evidence",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="cancelled", cancelled_at__isnull=False)
                    | (
                        ~models.Q(status="cancelled")
                        & models.Q(cancelled_at__isnull=True)
                    )
                ),
                name="identity_delivery_cancelled_timestamp",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        payload_destroyed_at__isnull=True,
                        payload_destruction_reason="",
                        encryption_algorithm=(INVITATION_DELIVERY_ENCRYPTION_ALGORITHM),
                        encrypted_payload__isnull=False,
                        wrapped_data_key__isnull=False,
                        payload_nonce__isnull=False,
                    )
                    & ~models.Q(encryption_key_id="")
                    & models.Q(payload_aad_digest__regex=r"^[0-9a-f]{64}$")
                    | models.Q(
                        payload_destroyed_at__isnull=False,
                        encrypted_payload__isnull=True,
                        wrapped_data_key__isnull=True,
                        payload_nonce__isnull=True,
                        encryption_algorithm="",
                        encryption_key_id="",
                        payload_aad_digest="",
                    )
                    & ~models.Q(payload_destruction_reason="")
                ),
                name="identity_delivery_envelope_lifecycle",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="delivered")
                    | models.Q(payload_destruction_reason="delivered")
                ),
                name="identity_delivered_payload_destroyed",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.challenge_id and (
            self.challenge.purpose != IdentityChallenge.Purpose.ACCOUNT_INVITATION
            or self.challenge.invitation_id != self.invitation_id
        ):
            raise ValidationError(
                "A platform delivery must match an invitation challenge.",
                code="identity_delivery_challenge_mismatch",
            )
        if (
            self.lease_expires_at
            and self.claimed_at
            and self.lease_expires_at <= self.claimed_at
        ):
            raise ValidationError(
                {"lease_expires_at": "A delivery lease must expire after claim."},
                code="identity_delivery_lease_invalid",
            )
        if (
            self.reconciled_at
            and self.reconciliation_required_at
            and self.reconciled_at < self.reconciliation_required_at
        ):
            raise ValidationError(
                {"reconciled_at": "Reconciliation cannot predate uncertainty."},
                code="identity_delivery_reconciliation_time_invalid",
            )
        if (
            self.cancelled_at
            and self.cancellation_requested_at
            and self.cancelled_at < self.cancellation_requested_at
        ):
            raise ValidationError(
                {"cancelled_at": "Cancellation cannot predate its request."},
                code="identity_delivery_cancellation_time_invalid",
            )
        if any(
            ord(character) < ASCII_CONTROL_LIMIT or ord(character) == ASCII_DELETE
            for character in self.provider_reference
        ):
            raise ValidationError(
                {"provider_reference": "Provider references cannot contain controls."},
                code="identity_delivery_provider_reference_invalid",
            )
        if self.payload_destroyed_at is None:
            if self.encryption_algorithm != INVITATION_DELIVERY_ENCRYPTION_ALGORITHM:
                raise ValidationError(
                    {"encryption_algorithm": "Use the supported envelope algorithm."},
                    code="identity_delivery_algorithm_invalid",
                )
            if (
                self.payload_nonce is None
                or len(bytes(self.payload_nonce)) != INVITATION_PAYLOAD_NONCE_BYTES
            ):
                raise ValidationError(
                    {"payload_nonce": "Use an exact 12-byte AES-GCM nonce."},
                    code="identity_delivery_nonce_invalid",
                )
            _validate_canonical_base64url(
                self.encrypted_payload,
                field_name="encrypted_payload",
                minimum_decoded=INVITATION_PAYLOAD_MIN_DECODED_BYTES,
                maximum_decoded=INVITATION_PAYLOAD_MAX_DECODED_BYTES,
            )
            _validate_canonical_base64url(
                self.wrapped_data_key,
                field_name="wrapped_data_key",
                minimum_decoded=INVITATION_WRAPPED_KEY_MIN_DECODED_BYTES,
                maximum_decoded=INVITATION_WRAPPED_KEY_MAX_DECODED_BYTES,
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Identity delivery controls require the retention workflow.",
            code="protected_platform_identity_delivery",
        )


class PlatformIdentityDeliveryAttempt(UUIDTimeStampedModel):
    """Append-only evidence for one leased identity delivery attempt."""

    class Outcome(models.TextChoices):
        DELIVERED = "delivered", "Delivered"
        TRANSIENT_FAILURE = "transient_failure", "Transient failure"
        PERMANENT_FAILURE = "permanent_failure", "Permanent failure"
        UNCERTAIN = "uncertain", "Uncertain provider result"
        LEASE_LOST = "lease_lost", "Lease lost"

    delivery = models.ForeignKey(
        PlatformIdentityDelivery,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    attempt_number = models.PositiveSmallIntegerField()
    lease_token = models.UUIDField()
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    outcome = models.CharField(max_length=24, choices=Outcome)
    provider_reference = models.CharField(max_length=160, blank=True)
    safe_error_code = models.CharField(
        max_length=120,
        blank=True,
        validators=(SAFE_DELIVERY_CODE_VALIDATOR,),
    )
    next_retry_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("delivery_id", "attempt_number", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("delivery", "attempt_number"),
                name="identity_delivery_attempt_number_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_number__gte=1, attempt_number__lte=100),
                name="identity_delivery_attempt_number_bounds",
            ),
            models.CheckConstraint(
                condition=models.Q(finished_at__gte=models.F("started_at")),
                name="identity_delivery_attempt_finished_after_start",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        outcome="delivered",
                        safe_error_code="",
                        next_retry_at__isnull=True,
                    )
                    | (
                        models.Q(
                            outcome="transient_failure",
                            next_retry_at__isnull=False,
                        )
                        & ~models.Q(safe_error_code="")
                    )
                    | (
                        models.Q(
                            outcome__in=(
                                "permanent_failure",
                                "uncertain",
                                "lease_lost",
                            ),
                            next_retry_at__isnull=True,
                        )
                        & ~models.Q(safe_error_code="")
                    )
                ),
                name="identity_delivery_attempt_outcome_evidence",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.delivery_id and self.attempt_number > self.delivery.max_attempts:
            raise ValidationError(
                {"attempt_number": "The attempt exceeds this delivery's limit."},
                code="identity_delivery_attempt_limit",
            )
        if self.next_retry_at and self.next_retry_at <= self.finished_at:
            raise ValidationError(
                {"next_retry_at": "A retry must be scheduled after this attempt."},
                code="identity_delivery_retry_time_invalid",
            )
        if any(
            ord(character) < ASCII_CONTROL_LIMIT or ord(character) == ASCII_DELETE
            for character in self.provider_reference
        ):
            raise ValidationError(
                {"provider_reference": "Provider references cannot contain controls."},
                code="identity_delivery_provider_reference_invalid",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Identity delivery attempts are append-only.",
                code="immutable_identity_delivery_attempt",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Identity delivery attempts are append-only.",
            code="immutable_identity_delivery_attempt",
        )


class PlatformIdentityDeliveryLateOutcome(UUIDTimeStampedModel):
    """Append-only provider result observed after an attempt lost its lease."""

    class Outcome(models.TextChoices):
        DELIVERED = "delivered", "Delivered"
        TRANSIENT_FAILURE = "transient_failure", "Transient failure"
        PERMANENT_FAILURE = "permanent_failure", "Permanent failure"
        UNCERTAIN = "uncertain", "Uncertain provider result"

    class Classification(models.TextChoices):
        LIFECYCLE_CANCELLED = "lifecycle_cancelled", "Lifecycle cancelled"
        LEASE_SUPERSEDED = "lease_superseded", "Lease superseded"
        TERMINAL_STATE = "terminal_state", "Delivery already terminal"

    delivery = models.ForeignKey(
        PlatformIdentityDelivery,
        on_delete=models.PROTECT,
        related_name="late_outcomes",
    )
    attempt_number = models.PositiveSmallIntegerField()
    lease_token = models.UUIDField()
    observed_at = models.DateTimeField()
    outcome = models.CharField(max_length=24, choices=Outcome)
    classification = models.CharField(max_length=24, choices=Classification)
    provider_reference = models.CharField(max_length=160, blank=True)
    safe_error_code = models.CharField(
        max_length=120,
        blank=True,
        validators=(SAFE_DELIVERY_CODE_VALIDATOR,),
    )

    class Meta:
        ordering = ("delivery_id", "attempt_number", "observed_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("delivery", "attempt_number", "lease_token"),
                name="identity_delivery_late_outcome_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_number__gte=1, attempt_number__lte=100),
                name="identity_delivery_late_attempt_bounds",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(outcome="delivered", safe_error_code="")
                        & ~models.Q(provider_reference="")
                    )
                    | (
                        models.Q(
                            outcome__in=(
                                "transient_failure",
                                "permanent_failure",
                                "uncertain",
                            ),
                            provider_reference="",
                        )
                        & ~models.Q(safe_error_code="")
                    )
                ),
                name="identity_delivery_late_outcome_evidence",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.delivery_id and self.attempt_number > self.delivery.max_attempts:
            raise ValidationError(
                {"attempt_number": "The attempt exceeds this delivery's limit."},
                code="identity_delivery_late_attempt_limit",
            )
        if any(
            ord(character) < ASCII_CONTROL_LIMIT or ord(character) == ASCII_DELETE
            for character in self.provider_reference
        ):
            raise ValidationError(
                {"provider_reference": "Provider references cannot contain controls."},
                code="identity_delivery_provider_reference_invalid",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Late delivery outcomes are append-only.",
                code="immutable_identity_delivery_late_outcome",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Late delivery outcomes are append-only.",
            code="immutable_identity_delivery_late_outcome",
        )


class PlatformIdentityDeliveryReconciliationReceipt(UUIDTimeStampedModel):
    """Append-only, scope-bound evidence for one operator reconciliation."""

    class Operation(models.TextChoices):
        RESOLVE_DELIVERED = "resolve_delivered", "Resolve as delivered"
        RESOLVE_RETRY = "resolve_retry", "Resolve and retry"

    inventory_control = models.ForeignKey(
        PlatformAccountInventoryControl,
        default=True,
        on_delete=models.PROTECT,
        related_name="delivery_reconciliation_receipts",
    )
    delivery = models.ForeignKey(
        PlatformIdentityDelivery,
        on_delete=models.PROTECT,
        related_name="reconciliation_receipts",
    )
    actor = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="platform_identity_delivery_reconciliations",
    )
    operation = models.CharField(max_length=24, choices=Operation)
    reason = models.CharField(max_length=240)
    retry_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=(SHA256_HEX_VALIDATOR,),
    )
    expected_version = models.PositiveBigIntegerField()
    result_version = models.PositiveBigIntegerField()
    correlation_id = models.UUIDField()
    source_channel = models.CharField(
        max_length=40,
        validators=(INVITATION_SOURCE_CHANNEL_VALIDATOR,),
    )

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("inventory_control", "actor", "retry_key"),
                name="identity_delivery_reconcile_retry_unique",
            ),
            models.UniqueConstraint(
                fields=("delivery", "result_version"),
                name="identity_reconcile_result_receipt_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                name="identity_delivery_reconcile_digest",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(expected_version__gt=0)
                    & models.Q(result_version=models.F("expected_version") + 1)
                ),
                name="identity_delivery_reconcile_version",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="identity_delivery_reconcile_reason",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.inventory_control_id is not True:
            raise ValidationError(
                {"inventory_control": "Use the platform account inventory scope."},
                code="identity_delivery_reconcile_scope_invalid",
            )
        if not self.reason.strip():
            raise ValidationError(
                {"reason": "A reconciliation requires a reason."},
                code="identity_delivery_reconcile_reason_required",
            )
        if self.actor_id and (
            not self.actor.is_active or not self.actor.is_platform_administrator
        ):
            raise ValidationError(
                {"actor": "Reconciliation requires a platform operator."},
                code="identity_delivery_reconcile_actor_invalid",
            )
        if self.delivery_id and self.result_version > self.delivery.aggregate_version:
            raise ValidationError(
                {"result_version": "The reconciled delivery version is not present."},
                code="identity_delivery_reconcile_result_invalid",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Delivery reconciliation receipts are append-only.",
                code="immutable_identity_delivery_reconciliation_receipt",
            )
        self.reason = self.reason.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Delivery reconciliation receipts are append-only.",
            code="immutable_identity_delivery_reconciliation_receipt",
        )


class PlatformInvitationRetentionPolicyControl(models.Model):
    """Migration-owner activated policy that must match deployment settings."""

    singleton = models.BooleanField(primary_key=True, default=True, editable=False)
    generation = models.CharField(max_length=32, default="retention-policy-v1")
    policy_id = models.CharField(
        max_length=120,
        validators=(RETENTION_POLICY_CODE_VALIDATOR,),
    )
    policy_version = models.PositiveIntegerField()
    policy_digest = models.CharField(
        max_length=64,
        validators=(SHA256_HEX_VALIDATOR,),
    )
    jurisdiction_code = models.CharField(max_length=40)
    policy_approved_by_reference = models.CharField(
        max_length=120,
        validators=(RETENTION_POLICY_CODE_VALIDATOR,),
    )
    policy_approved_at = models.DateTimeField()
    trigger = models.CharField(max_length=32)
    retention_period_days = models.PositiveIntegerField()
    action = models.CharField(max_length=48)
    activated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(singleton=True),
                name="identity_inv_ret_policy_singleton",
            ),
            models.CheckConstraint(
                condition=models.Q(policy_version__gt=0),
                name="identity_inv_ret_control_ver_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(retention_period_days__lte=36_500),
                name="identity_inv_ret_control_period",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        generation="retention-policy-v1",
                        trigger="terminal_transition",
                        action="anonymize_abandoned_invitation_contact",
                        policy_digest__regex=r"^[0-9a-f]{64}$",
                        policy_id__regex=r"^[a-z0-9][a-z0-9_.:-]{0,119}$",
                        jurisdiction_code__regex=r"^[A-Z0-9][A-Z0-9_.:-]{0,39}$",
                        policy_approved_by_reference__regex=(
                            r"^[a-z0-9][a-z0-9_.:-]{0,119}$"
                        ),
                    )
                    & models.Q(policy_approved_at__lte=models.F("activated_at"))
                ),
                name="identity_inv_ret_control_contract",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.policy_id}:v{self.policy_version}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.singleton = True
        self.policy_id = self.policy_id.strip().lower()
        self.jurisdiction_code = self.jurisdiction_code.strip().upper()
        self.policy_approved_by_reference = (
            self.policy_approved_by_reference.strip().lower()
        )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "The activated invitation retention policy is a deployment control.",
            code="protected_invitation_retention_policy_control",
        )

    def clean(self) -> None:
        super().clean()
        if (
            self.generation != "retention-policy-v1"
            or self.trigger != "terminal_transition"
            or self.action != "anonymize_abandoned_invitation_contact"
            or self.policy_approved_at > self.activated_at
        ):
            raise ValidationError(
                "Use one complete approved invitation retention policy.",
                code="invitation_retention_policy_control_invalid",
            )


class PlatformInvitationRetentionHold(UUIDTimeStampedModel):
    """Reasoned, auditable hold that prevents invitation contact disposal."""

    invitation = models.ForeignKey(
        PlatformAccountInvitation,
        on_delete=models.PROTECT,
        related_name="retention_holds",
    )
    reference_code = models.CharField(
        max_length=120,
        validators=(RETENTION_POLICY_CODE_VALIDATOR,),
    )
    reason_code = models.CharField(
        max_length=120,
        validators=(RETENTION_POLICY_CODE_VALIDATOR,),
    )
    placed_at = models.DateTimeField()
    placed_by = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="platform_invitation_retention_holds_placed",
    )
    place_correlation_id = models.UUIDField()
    active = models.BooleanField(default=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="platform_invitation_retention_holds_released",
    )
    release_reason_code = models.CharField(
        max_length=120,
        blank=True,
        validators=(RETENTION_POLICY_CODE_VALIDATOR,),
    )
    release_correlation_id = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ("invitation_id", "placed_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("invitation",),
                condition=models.Q(active=True),
                name="identity_one_active_inv_ret_hold",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        active=True,
                        released_at__isnull=True,
                        released_by__isnull=True,
                        release_reason_code="",
                        release_correlation_id__isnull=True,
                    )
                    | (
                        models.Q(
                            active=False,
                            released_at__isnull=False,
                            released_by__isnull=False,
                            release_correlation_id__isnull=False,
                        )
                        & ~models.Q(release_reason_code="")
                    )
                ),
                name="identity_inv_ret_hold_release_state",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.placed_by_id and (
            not self.placed_by.is_active or not self.placed_by.is_platform_administrator
        ):
            raise ValidationError(
                {"placed_by": "A hold requires an active platform administrator."},
                code="invitation_retention_hold_actor_invalid",
            )
        released_by = self.released_by if self.released_by_id else None
        if released_by is not None and (
            not released_by.is_active or not released_by.is_platform_administrator
        ):
            raise ValidationError(
                {"released_by": "A release requires an active platform administrator."},
                code="invitation_retention_release_actor_invalid",
            )
        if self.released_at and self.released_at < self.placed_at:
            raise ValidationError(
                {"released_at": "A hold cannot be released before it was placed."},
                code="invitation_retention_hold_chronology_invalid",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.reference_code = self.reference_code.strip().lower()
        self.reason_code = self.reason_code.strip().lower()
        self.release_reason_code = self.release_reason_code.strip().lower()
        if not self._state.adding:
            current = type(self).objects.filter(id=self.id).first()
            if current is None or not current.active:
                raise ValidationError(
                    "Released invitation retention holds are immutable.",
                    code="immutable_invitation_retention_hold",
                )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Invitation retention holds are retained as legal evidence.",
            code="protected_invitation_retention_hold",
        )


class PlatformInvitationRetentionAssessment(UUIDTimeStampedModel):
    """Current value-minimized outcome of inspecting one retention target."""

    class ResultCode(models.TextChoices):
        DISPOSED = "disposed", "Disposed"
        NOT_DUE = "not_due", "Not due"
        ACTIVE_HOLD = "active_hold", "Active hold"
        ACCOUNT_STATE = "account_state", "Account state blocks disposition"
        SECURITY_HISTORY = (
            "security_history",
            "Security history blocks disposition",
        )
        CHALLENGE_RELATIONSHIP = (
            "challenge_relationship",
            "Another challenge relationship blocks disposition",
        )
        ACCOUNT_RELATIONSHIP = (
            "account_relationship",
            "Another account relationship blocks disposition",
        )
        ADDITIONAL_INVITATION = (
            "additional_invitation",
            "Another invitation blocks disposition",
        )
        ACTIVE_CHALLENGE = (
            "active_challenge",
            "An active challenge blocks disposition",
        )
        CHALLENGE_STATE = (
            "challenge_state",
            "Challenge state blocks disposition",
        )
        DELIVERY_UNRESOLVED = (
            "delivery_unresolved",
            "Delivery state blocks disposition",
        )

    invitation = models.OneToOneField(
        PlatformAccountInvitation,
        on_delete=models.PROTECT,
        related_name="retention_assessment",
    )
    policy_digest = models.CharField(
        max_length=64,
        validators=(SHA256_HEX_VALIDATOR,),
    )
    terminal_version = models.PositiveBigIntegerField()
    assessment_version = models.PositiveBigIntegerField(default=1, editable=False)
    safe_result_code = models.CharField(max_length=64, choices=ResultCode)
    assessed_at = models.DateTimeField()

    class Meta:
        ordering = ("assessed_at", "id")
        indexes = [
            models.Index(
                fields=("safe_result_code", "assessed_at", "id"),
                name="id_inv_ret_assess_code_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(terminal_version__gt=0),
                name="identity_inv_ret_assess_terminal_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(assessment_version__gt=0),
                name="identity_inv_ret_assess_version_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    safe_result_code__in=(
                        "disposed",
                        "not_due",
                        "active_hold",
                        "account_state",
                        "security_history",
                        "challenge_relationship",
                        "account_relationship",
                        "additional_invitation",
                        "active_challenge",
                        "challenge_state",
                        "delivery_unresolved",
                    )
                ),
                name="identity_inv_ret_assess_result_code",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            current = (
                type(self)
                .objects.filter(id=self.id)
                .values_list("safe_result_code", flat=True)
                .first()
            )
            if current == self.ResultCode.DISPOSED:
                raise ValidationError(
                    "Disposed invitation retention assessments are terminal.",
                    code="immutable_disposed_invitation_retention_assessment",
                )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Invitation retention assessments are controlled evidence.",
            code="protected_invitation_retention_assessment",
        )


class PlatformInvitationRetentionReceipt(UUIDTimeStampedModel):
    """Append-only proof that abandoned invitation contact was anonymized."""

    class Trigger(models.TextChoices):
        TERMINAL_TRANSITION = "terminal_transition", "Terminal transition"

    class Action(models.TextChoices):
        ANONYMIZE_ABANDONED_CONTACT = (
            "anonymize_abandoned_invitation_contact",
            "Anonymize abandoned invitation contact",
        )

    inventory_control = models.ForeignKey(
        PlatformAccountInventoryControl,
        default=True,
        on_delete=models.PROTECT,
        related_name="invitation_retention_receipts",
    )
    invitation = models.OneToOneField(
        PlatformAccountInvitation,
        on_delete=models.PROTECT,
        related_name="retention_receipt",
    )
    policy_id = models.CharField(
        max_length=120,
        validators=(RETENTION_POLICY_CODE_VALIDATOR,),
    )
    policy_version = models.PositiveIntegerField()
    policy_digest = models.CharField(
        max_length=64,
        validators=(SHA256_HEX_VALIDATOR,),
    )
    jurisdiction_code = models.CharField(max_length=40)
    policy_approved_by_reference = models.CharField(
        max_length=120,
        validators=(RETENTION_POLICY_CODE_VALIDATOR,),
    )
    policy_approved_at = models.DateTimeField()
    trigger = models.CharField(max_length=32, choices=Trigger)
    retention_period_days = models.PositiveIntegerField()
    terminal_version = models.PositiveBigIntegerField()
    trigger_at = models.DateTimeField()
    due_at = models.DateTimeField()
    action = models.CharField(max_length=48, choices=Action)
    applied_at = models.DateTimeField()
    correlation_id = models.UUIDField()
    source_channel = models.CharField(
        max_length=40,
        validators=(INVITATION_SOURCE_CHANNEL_VALIDATOR,),
    )
    safe_result_code = models.CharField(
        max_length=120,
        validators=(RETENTION_POLICY_CODE_VALIDATOR,),
    )

    class Meta:
        ordering = ("applied_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(policy_version__gt=0),
                name="identity_inv_ret_policy_version_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(retention_period_days__lte=36_500),
                name="identity_inv_ret_period_bound",
            ),
            models.CheckConstraint(
                condition=models.Q(terminal_version__gt=0),
                name="identity_inv_ret_terminal_ver_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(due_at__gte=models.F("trigger_at")),
                name="identity_inv_ret_due_after_trigger",
            ),
            models.CheckConstraint(
                condition=models.Q(applied_at__gte=models.F("due_at")),
                name="identity_inv_ret_apply_after_due",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.inventory_control_id is not True:
            raise ValidationError(
                {"inventory_control": "Use the platform account inventory scope."},
                code="invitation_retention_receipt_scope_invalid",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Invitation retention receipts are append-only.",
                code="immutable_invitation_retention_receipt",
            )
        self.policy_id = self.policy_id.strip().lower()
        self.jurisdiction_code = self.jurisdiction_code.strip().upper()
        self.policy_approved_by_reference = (
            self.policy_approved_by_reference.strip().lower()
        )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Invitation retention receipts are append-only.",
            code="immutable_invitation_retention_receipt",
        )


class PlatformInvitationSchedulerRun(UUIDTimeStampedModel):
    """Append-only, value-minimized successful scheduler heartbeat."""

    class Kind(models.TextChoices):
        DELIVERY = "delivery", "Invitation delivery"
        EXPIRY = "expiry", "Invitation expiry"
        RETENTION = "retention", "Invitation retention"

    class Generation(models.TextChoices):
        DELIVERY_V1 = "delivery-v1", "Delivery worker v1"
        EXPIRY_V1 = "expiry-v1", "Expiry scheduler v1"
        RETENTION_V1 = "retention-v1", "Retention scheduler v1 (historical)"
        RETENTION_V2 = "retention-v2", "Retention scheduler v2"

    kind = models.CharField(max_length=16, choices=Kind)
    generation = models.CharField(max_length=24, choices=Generation)
    ran_at = models.DateTimeField(default=timezone.now)
    processed_count = models.PositiveIntegerField(default=0)
    remaining_count = models.PositiveBigIntegerField(default=0)
    private_key_coverage_complete = models.BooleanField(default=False)
    policy_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(SHA256_HEX_VALIDATOR,),
    )
    inspected_count = models.PositiveIntegerField(default=0)
    blocked_count = models.PositiveIntegerField(default=0)
    held_count = models.PositiveIntegerField(default=0)
    retention_cursor_transition_at = models.DateTimeField(null=True, blank=True)
    retention_cursor_invitation_id = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ("-ran_at", "-id")
        indexes = [
            models.Index(
                fields=("kind", "-ran_at", "-id"),
                name="id_inv_scheduler_run_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(processed_count__lte=1_000),
                name="identity_inv_scheduler_processed_bound",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind="delivery",
                        generation="delivery-v1",
                        private_key_coverage_complete=True,
                        policy_digest="",
                        inspected_count=0,
                        blocked_count=0,
                        held_count=0,
                        retention_cursor_transition_at__isnull=True,
                        retention_cursor_invitation_id__isnull=True,
                    )
                    | models.Q(
                        kind="expiry",
                        generation="expiry-v1",
                        private_key_coverage_complete=False,
                        policy_digest="",
                        inspected_count=0,
                        blocked_count=0,
                        held_count=0,
                        retention_cursor_transition_at__isnull=True,
                        retention_cursor_invitation_id__isnull=True,
                    )
                    | (
                        models.Q(
                            kind="retention",
                            generation="retention-v1",
                            private_key_coverage_complete=False,
                            inspected_count=0,
                            blocked_count=0,
                            held_count=0,
                            retention_cursor_transition_at__isnull=True,
                            retention_cursor_invitation_id__isnull=True,
                        )
                        & models.Q(policy_digest__regex=r"^[0-9a-f]{64}$")
                    )
                    | (
                        models.Q(
                            kind="retention",
                            generation="retention-v2",
                            private_key_coverage_complete=False,
                            inspected_count__lte=100,
                            blocked_count__lte=models.F("inspected_count"),
                            held_count__lte=models.F("inspected_count"),
                            processed_count__lte=models.F("inspected_count"),
                        )
                        & models.Q(policy_digest__regex=r"^[0-9a-f]{64}$")
                        & (
                            models.Q(
                                inspected_count=0,
                                retention_cursor_transition_at__isnull=True,
                                retention_cursor_invitation_id__isnull=True,
                            )
                            | (
                                models.Q(inspected_count__gt=0)
                                & models.Q(
                                    retention_cursor_transition_at__isnull=False,
                                    retention_cursor_invitation_id__isnull=False,
                                )
                            )
                        )
                    )
                ),
                name="identity_inv_scheduler_kind_evidence",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(kind="retention")
                    | models.Q(generation="retention-v1")
                    | models.Q(
                        inspected_count__gte=(
                            models.F("processed_count")
                            + models.F("blocked_count")
                            + models.F("held_count")
                        )
                    )
                ),
                name="identity_inv_ret_run_count_consistency",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.kind == self.Kind.DELIVERY:
            expected: str | None = self.Generation.DELIVERY_V1
        elif self.kind == self.Kind.EXPIRY:
            expected = self.Generation.EXPIRY_V1
        elif self.kind == self.Kind.RETENTION:
            expected = self.Generation.RETENTION_V2
        else:
            expected = None
        if expected is None or self.generation != expected:
            raise ValidationError(
                {"generation": "Use the scheduler generation for this run kind."},
                code="invitation_scheduler_generation_invalid",
            )
        if self.private_key_coverage_complete != (self.kind == self.Kind.DELIVERY):
            raise ValidationError(
                {
                    "private_key_coverage_complete": (
                        "Only a delivery run records complete private-key coverage."
                    )
                },
                code="invitation_scheduler_key_coverage_invalid",
            )
        if self.kind == self.Kind.RETENTION:
            if not self.policy_digest:
                raise ValidationError(
                    {"policy_digest": "Retention runs require the policy digest."},
                    code="invitation_scheduler_policy_digest_required",
                )
            cursor_is_complete = (
                self.retention_cursor_transition_at is not None
                and self.retention_cursor_invitation_id is not None
            )
            if cursor_is_complete != (self.inspected_count > 0):
                raise ValidationError(
                    {"inspected_count": "Retention cursor evidence is incomplete."},
                    code="invitation_scheduler_retention_cursor_invalid",
                )
            if (
                self.retention_cursor_transition_at is not None
                and self.retention_cursor_transition_at > self.ran_at
            ):
                raise ValidationError(
                    {"retention_cursor_transition_at": "The cursor cannot be future."},
                    code="invitation_scheduler_retention_cursor_time_invalid",
                )
            if (
                self.processed_count + self.blocked_count + self.held_count
                > self.inspected_count
            ):
                raise ValidationError(
                    {"inspected_count": "Retention run counts are inconsistent."},
                    code="invitation_scheduler_retention_counts_invalid",
                )
        elif self.policy_digest:
            raise ValidationError(
                {"policy_digest": "Only retention runs record a policy digest."},
                code="invitation_scheduler_policy_digest_invalid",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Invitation scheduler runs are append-only.",
                code="immutable_invitation_scheduler_run",
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Invitation scheduler runs follow the identity retention workflow.",
            code="protected_invitation_scheduler_run",
        )


class AccountSession(UUIDTimeStampedModel):
    """User-visible session inventory without exposing the session bearer key."""

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="account_sessions",
    )
    session = models.OneToOneField(
        Session,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="maru_inventory",
    )
    session_key_digest = models.CharField(max_length=64, unique=True, editable=False)
    label = models.CharField(max_length=120)
    created_channel = models.CharField(max_length=40)
    last_seen_at = models.DateTimeField()
    step_up_verified_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("-last_seen_at", "-id")
        indexes = [
            models.Index(
                fields=("account", "revoked_at", "last_seen_at"),
                name="identity_session_inventory_idx",
            )
        ]

    @property
    def is_active_session(self) -> bool:
        return self.revoked_at is None and self.session_id is not None


class IdentityAbuseBucket(UUIDTimeStampedModel):
    """Bounded request counter keyed by a non-reversible request fingerprint."""

    flow = models.CharField(max_length=40)
    subject_digest = models.CharField(max_length=64)
    window_started_at = models.DateTimeField()
    attempt_count = models.PositiveIntegerField(default=0)
    blocked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("flow", "subject_digest", "window_started_at"),
                name="identity_abuse_bucket_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=("flow", "subject_digest", "window_started_at"),
                name="identity_abuse_lookup_idx",
            )
        ]


class AccountRestriction(UUIDTimeStampedModel):
    """Organizer/edition-scoped restriction, separate from platform login state."""

    class Kind(models.TextChoices):
        REGISTRATION = "registration", "Registration"
        ATTENDANCE = "attendance", "Attendance"
        PUBLIC_PROFILE = "public_profile", "Public attendee profile"
        CREDENTIAL = "credential", "Credential"
        COMMUNICATION = "communication", "Communication"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="account_restrictions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="account_restrictions",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="restrictions",
    )
    kind = models.CharField(max_length=24, choices=Kind)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.ACTIVE,
    )
    reason_code = models.CharField(max_length=80)
    attendee_message = models.CharField(max_length=320)
    internal_reference = models.CharField(max_length=120, blank=True)
    notify_account = models.BooleanField(default=True)
    effective_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    consequences_applied_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="issued_account_restrictions",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_account_restrictions",
    )
    revocation_reason = models.CharField(max_length=320, blank=True)

    class Meta:
        ordering = ("-effective_at", "-id")
        indexes = [
            models.Index(
                fields=("organization", "account", "kind", "status"),
                name="identity_restriction_scope_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if (
            self.edition_id
            and self.edition is not None
            and self.edition.organization_id != self.organization_id
        ):
            raise ValidationError(
                "A restriction edition must belong to its organization.",
                code="restriction_scope_mismatch",
            )
        if self.expires_at and self.expires_at <= self.effective_at:
            raise ValidationError(
                {"expires_at": "Expiry must be after the effective time."},
                code="restriction_expiry_invalid",
            )
        revoked = self.status == self.Status.REVOKED
        if revoked != bool(self.revoked_at and self.revoked_by_id):
            raise ValidationError(
                "Revoked restrictions require complete revocation evidence.",
                code="restriction_revocation_evidence",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.reason_code = self.reason_code.strip().lower()
        self.attendee_message = self.attendee_message.strip()
        self.internal_reference = self.internal_reference.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        _ = args, kwargs
        raise ValidationError(
            "Restrictions are revoked, never deleted.",
            code="protected_account_restriction",
        )


class RestrictionAppeal(UUIDTimeStampedModel):
    """Attendee appeal text kept outside ordinary registration projections."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        UPHELD = "upheld", "Restriction upheld"
        RESOLVED = "resolved", "Restriction changed"

    restriction = models.ForeignKey(
        AccountRestriction,
        on_delete=models.PROTECT,
        related_name="appeals",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="restriction_appeals",
    )
    statement = models.TextField(max_length=4000)
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN)
    submitted_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="decided_restriction_appeals",
    )
    decision_summary = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("-submitted_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("restriction", "account"),
                condition=models.Q(status="open"),
                name="one_open_appeal_per_restriction",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.restriction_id and self.account_id != self.restriction.account_id:
            raise ValidationError(
                "Only the restricted account may own this appeal.",
                code="appeal_account_mismatch",
            )
        decided = self.status != self.Status.OPEN
        if decided != bool(self.decided_at and self.decided_by_id):
            raise ValidationError(
                "A decided appeal requires complete decision evidence.",
                code="appeal_decision_evidence",
            )


ACCOUNT_RESTRICTION_KIND_CHOICES = AccountRestriction.Kind.choices
ACTIVE_REVOKED_STATUS_CHOICES = AccountRestriction.Status.choices
