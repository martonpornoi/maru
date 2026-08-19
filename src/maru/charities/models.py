"""Organizer-owned beneficiary profiles and edition review evidence."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, RegexValidator
from django.db import models
from django.db.models.functions import Lower

from maru.core.localization import validate_country_code
from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_lowercase_slug

from .writer_boundary import require_charity_writer

MAX_CHARITY_REASON_LENGTH = 1_000
MAX_CHARITY_COMMENT_LENGTH = 5_000
MAX_PUBLIC_MEDIA_REFERENCES = 24

_SHA256_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-f]{64}$",
    message="Use a lowercase SHA-256 digest.",
    code="invalid_charity_digest",
)
_PHONE_VALIDATOR = RegexValidator(
    regex=r"^\+[1-9]\d{6,14}$",
    message="Enter an international telephone number such as +431234567.",
)


class _ClosedCharityModel(UUIDTimeStampedModel):
    """Reject ORM writes that bypass the charity application service."""

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        require_charity_writer()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValidationError(
            "Charity records are retained; use a lifecycle command.",
            code="protected_charity_record",
        )


class _AppendOnlyCharityModel(_ClosedCharityModel):
    """Create-only evidence retained with its aggregate."""

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValidationError(
                "Charity evidence is append-only.",
                code="immutable_charity_evidence",
            )
        super().save(*args, **kwargs)


class CharityPartner(_ClosedCharityModel):
    """Reusable beneficiary profile owned by one organizer, never a tenant."""

    class Lifecycle(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="charity_partners",
    )
    slug = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    legal_name = models.CharField(max_length=240)
    imprint_name = models.CharField(max_length=240, blank=True)
    public_name = models.CharField(max_length=200)
    short_description = models.CharField(max_length=500, blank=True)
    description = models.TextField(max_length=5_000, blank=True)
    location_name = models.CharField(max_length=240, blank=True)
    postal_address = models.TextField(max_length=1_000, blank=True)
    country_code = models.CharField(
        max_length=2,
        blank=True,
        validators=(validate_country_code,),
    )
    website_url = models.URLField(blank=True)
    contact_email = models.EmailField(blank=True, validators=(EmailValidator(),))
    contact_phone = models.CharField(
        max_length=16,
        blank=True,
        validators=(_PHONE_VALIDATOR,),
    )
    lifecycle = models.CharField(
        max_length=16,
        choices=Lifecycle,
        default=Lifecycle.DRAFT,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="charity_partners_created",
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="charity_partners_modified",
    )

    class Meta:
        ordering = ("organization_id", "public_name", "id")
        constraints = [
            models.UniqueConstraint(
                models.F("organization"),
                Lower("slug"),
                name="charity_partner_org_slug_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gt=0),
                name="charity_partner_version_pos",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.slug = self.slug.lower()
        self.country_code = self.country_code.upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.public_name


class CharityPartnerMedia(_ClosedCharityModel):
    """Governed source and approved rendition references for one partner."""

    class Kind(models.TextChoices):
        LOGO = "logo", "Logo"
        PHOTO = "photo", "Photo"

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        WITHDRAWN = "withdrawn", "Withdrawn"

    partner = models.ForeignKey(
        CharityPartner,
        on_delete=models.PROTECT,
        related_name="media_references",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="charity_media_references",
    )
    kind = models.CharField(max_length=16, choices=Kind)
    source_reference = models.CharField(max_length=1_000)
    public_reference = models.CharField(max_length=1_000, blank=True)
    owner_name = models.CharField(max_length=240)
    license_basis = models.CharField(max_length=500)
    usage_scope = models.CharField(max_length=500)
    attribution = models.CharField(max_length=500, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    review_status = models.CharField(
        max_length=16,
        choices=ReviewStatus,
        default=ReviewStatus.PENDING,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="charity_media_submitted",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="charity_media_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("partner_id", "kind", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gt=0),
                name="charity_media_version_pos",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        review_status="pending",
                        reviewed_by__isnull=True,
                        reviewed_at__isnull=True,
                    )
                    | models.Q(
                        review_status__in=("approved", "withdrawn"),
                        reviewed_by__isnull=False,
                        reviewed_at__isnull=False,
                    )
                ),
                name="charity_media_review_evidence",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.partner_id and self.partner.organization_id != self.organization_id:
            raise ValidationError(
                "Charity media must remain in its partner's organizer scope.",
                code="charity_media_scope_mismatch",
            )
        if (
            self.review_status == self.ReviewStatus.APPROVED
            and not self.public_reference
        ):
            raise ValidationError(
                {"public_reference": "An approved rendition reference is required."}
            )


class CharitySelection(_ClosedCharityModel):
    """One beneficiary proposed for one edition and responsible department."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        SUBMITTED = "submitted", "Submitted"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"

    class PublicationState(models.TextChoices):
        UNPUBLISHED = "unpublished", "Unpublished"
        PUBLISHED = "published", "Published"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="charity_selections",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="charity_selections",
    )
    responsible_department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="charity_selections",
    )
    partner = models.ForeignKey(
        CharityPartner,
        on_delete=models.PROTECT,
        related_name="edition_selections",
    )
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.PROPOSED,
    )
    publication_state = models.CharField(
        max_length=16,
        choices=PublicationState,
        default=PublicationState.UNPUBLISHED,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    publication_number = models.PositiveIntegerField(default=0, editable=False)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="charity_selections_proposed",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("edition_id", "partner__public_name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "partner"),
                name="charity_selection_edition_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gt=0),
                name="charity_selection_version_pos",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(publication_state="unpublished")
                    | models.Q(status="confirmed")
                ),
                name="charity_publish_confirmed_only",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        edition = self.edition if self.edition_id else None
        partner = self.partner if self.partner_id else None
        if edition is not None and edition.organization_id != self.organization_id:
            raise ValidationError(
                "Charity selection must match its edition organization.",
                code="charity_selection_edition_scope",
            )
        if partner is not None and partner.organization_id != self.organization_id:
            raise ValidationError(
                "Charity selection must use an organizer-owned partner.",
                code="charity_selection_partner_scope",
            )
        if self.responsible_department_id and (
            self.responsible_department.organization_id != self.organization_id
            or self.responsible_department.edition_id != self.edition_id
            or self.responsible_department.retired_at is not None
        ):
            raise ValidationError(
                "Charity selection must use a current Department in its exact edition.",
                code="charity_selection_department_scope",
            )


class CharitySelectionTimelineEntry(_AppendOnlyCharityModel):
    """Purpose-scoped append-only review, comment, and publication history."""

    class Kind(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        STATUS = "status", "Status decision"
        PRIVATE_COMMENT = "private_comment", "Private comment"
        PUBLICATION = "publication", "Publication decision"

    selection = models.ForeignKey(
        CharitySelection,
        on_delete=models.PROTECT,
        related_name="timeline_entries",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="charity_timeline_entries",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="charity_timeline_entries",
    )
    sequence = models.PositiveBigIntegerField()
    kind = models.CharField(max_length=24, choices=Kind)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="charity_timeline_entries_acted",
    )
    occurred_at = models.DateTimeField()
    from_status = models.CharField(
        max_length=16,
        choices=CharitySelection.Status,
        blank=True,
    )
    to_status = models.CharField(
        max_length=16,
        choices=CharitySelection.Status,
        blank=True,
    )
    from_publication_state = models.CharField(
        max_length=16,
        choices=CharitySelection.PublicationState,
        blank=True,
    )
    to_publication_state = models.CharField(
        max_length=16,
        choices=CharitySelection.PublicationState,
        blank=True,
    )
    reason = models.CharField(max_length=MAX_CHARITY_REASON_LENGTH, blank=True)
    private_comment = models.TextField(
        max_length=MAX_CHARITY_COMMENT_LENGTH, blank=True
    )

    class Meta:
        ordering = ("selection_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("selection", "sequence"),
                name="charity_timeline_sequence_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gt=0),
                name="charity_timeline_sequence_pos",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        selection = self.selection if self.selection_id else None
        if selection is not None and (
            selection.organization_id != self.organization_id
            or selection.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Charity timeline evidence must remain in the selection scope.",
                code="charity_timeline_scope_mismatch",
            )
        if self.kind == self.Kind.PRIVATE_COMMENT and not self.private_comment:
            raise ValidationError({"private_comment": "Enter a private comment."})
        if self.kind != self.Kind.PRIVATE_COMMENT and not self.reason:
            raise ValidationError({"reason": "Record a reason for this decision."})


class CharityPublicationSnapshot(_AppendOnlyCharityModel):
    """Immutable minimized fields explicitly approved for public projection."""

    selection = models.ForeignKey(
        CharitySelection,
        on_delete=models.PROTECT,
        related_name="publication_snapshots",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="charity_publication_snapshots",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="charity_publication_snapshots",
    )
    publication_number = models.PositiveIntegerField()
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="charity_publications_approved",
    )
    approved_at = models.DateTimeField()
    public_name = models.CharField(max_length=200)
    imprint_name = models.CharField(max_length=240, blank=True)
    short_description = models.CharField(max_length=500, blank=True)
    location_name = models.CharField(max_length=240, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    website_url = models.URLField(blank=True)
    media_ids = ArrayField(
        models.UUIDField(),
        default=list,
        size=MAX_PUBLIC_MEDIA_REFERENCES,
    )

    class Meta:
        ordering = ("selection_id", "publication_number", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("selection", "publication_number"),
                name="charity_publication_number_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(publication_number__gt=0),
                name="charity_publication_number_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(media_ids__len__lte=MAX_PUBLIC_MEDIA_REFERENCES),
                name="charity_public_media_bounded",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.selection_id and (
            self.selection.organization_id != self.organization_id
            or self.selection.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Charity publication must remain in the selection scope.",
                code="charity_publication_scope_mismatch",
            )


class CharityCommandReceipt(_AppendOnlyCharityModel):
    """Immutable, minimized idempotency evidence for successful commands."""

    class Operation(models.TextChoices):
        PARTNER_CREATE = "partner_create", "Create partner"
        PARTNER_UPDATE = "partner_update", "Update partner"
        MEDIA_ADD = "media_add", "Add media"
        MEDIA_APPROVE = "media_approve", "Approve media"
        MEDIA_WITHDRAW = "media_withdraw", "Withdraw media"
        SELECTION_PROPOSE = "selection_propose", "Propose selection"
        SELECTION_SUBMIT = "selection_submit", "Submit selection"
        SELECTION_CONFIRM = "selection_confirm", "Confirm selection"
        SELECTION_REJECT = "selection_reject", "Reject selection"
        SELECTION_COMMENT = "selection_comment", "Comment on selection"
        SELECTION_PUBLISH = "selection_publish", "Publish selection"
        SELECTION_WITHDRAW = "selection_withdraw", "Withdraw publication"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="charity_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="charity_command_receipts",
    )
    partner = models.ForeignKey(
        CharityPartner,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    selection = models.ForeignKey(
        CharitySelection,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    operation = models.CharField(max_length=32, choices=Operation)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="charity_commands_acted",
    )
    idempotency_key = models.UUIDField()
    request_digest = models.CharField(max_length=64, validators=(_SHA256_VALIDATOR,))
    resulting_version = models.PositiveBigIntegerField()
    result_object_id = models.UUIDField()
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)

    class Meta:
        ordering = ("organization_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("actor", "operation", "idempotency_key"),
                name="charity_command_retry_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(resulting_version__gt=0),
                name="charity_receipt_version_pos",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        edition = self.edition if self.edition_id else None
        partner = self.partner if self.partner_id else None
        selection = self.selection if self.selection_id else None
        if edition is not None and edition.organization_id != self.organization_id:
            raise ValidationError(
                "Charity command receipt edition is outside its organizer scope.",
                code="charity_receipt_edition_scope",
            )
        if partner is not None and partner.organization_id != self.organization_id:
            raise ValidationError(
                "Charity command receipt partner is outside its organizer scope.",
                code="charity_receipt_partner_scope",
            )
        if selection is not None and (
            selection.organization_id != self.organization_id
            or selection.edition_id != self.edition_id
        ):
            raise ValidationError(
                "Charity command receipt selection is outside its edition scope.",
                code="charity_receipt_selection_scope",
            )
