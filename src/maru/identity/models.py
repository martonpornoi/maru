"""Authentication-facing platform account and scoped access safety records."""

from typing import Any, ClassVar
from uuid import uuid4

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from maru.core.models import UUIDTimeStampedModel
from maru.identity.managers import AccountManager

ASCII_CONTROL_LIMIT = 32
ASCII_DELETE = 127


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

    objects = AccountManager()

    EMAIL_FIELD = "email"
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        ordering = ("date_joined", "id")
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

    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        PERMANENT_FAILED = "permanent_failed", "Permanent failure"

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="identity_challenges",
    )
    purpose = models.CharField(max_length=24, choices=Purpose)
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    email_snapshot = models.EmailField()
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    request_fingerprint = models.CharField(max_length=64, editable=False)
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
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.email_snapshot.casefold() != self.account.email.casefold():
            raise ValidationError(
                "The challenge contact does not match the account.",
                code="identity_challenge_contact_mismatch",
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
