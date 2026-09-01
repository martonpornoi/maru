"""Versioned application definitions and provenance-preserving responses."""
# ruff: noqa: E501, PLR0912, PLR2004, SIM102

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, override

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from maru.applications.adoption import profile_allows_application_reviewer_role
from maru.core.models import UUIDTimeStampedModel
from maru.core.validators import validate_lowercase_slug
from maru.identity.policies import validate_convention_subject

from .programme_import_writer_boundary import require_programme_import_writer
from .programme_writer_boundary import require_programme_application_writer

if TYPE_CHECKING:
    from collections.abc import Iterable

MAX_DEFINITION_CARDINALITY = 100
MAX_QUESTION_OPTIONS = 100
MAX_SECTIONS = 100
MAX_QUESTIONS = 500
MAX_ANSWER_BYTES = 65_536

POLICY_CODE_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_.:-]{2,119}$",
    message="Use a stable versioned policy code.",
    code="invalid_application_policy_code",
)
REFERENCE_KIND_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_.:-]{0,79}$",
    message="Use a registered reference kind.",
    code="invalid_application_reference_kind",
)
PROGRAMME_DIGEST_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-f]{64}\Z",
    message="Use a lower-case SHA-256 digest.",
    code="invalid_programme_application_digest",
)
PROGRAMME_SOURCE_CHANNEL_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_-]*\Z",
    message="Use a registered lower-case source channel.",
    code="invalid_programme_application_source_channel",
)
PROGRAMME_IMPORT_SOURCE_SYSTEM_VALIDATOR = RegexValidator(
    regex=r"^[a-z][a-z0-9_.:-]{0,79}\Z",
    message="Use a registered lower-case import source system.",
    code="invalid_programme_import_source_system",
)
PROGRAMME_IMPORT_SOURCE_KEY_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}\Z",
    message="Use a bounded ASCII Programme-import source key.",
    code="invalid_programme_import_source_key",
)
PROGRAMME_IMPORT_SAFE_FIELD_KEYS = (
    "configuration",
    "definition",
    "answers",
    "lead_action_required",
    "selection",
)
PROGRAMME_IMPORT_REASON_CODES = (
    "source_already_applied",
    "source_digest_conflict",
    "definition_code_conflict",
    "call_dependency_unavailable",
    "call_dependency_not_active",
    "proposal_mapping_invalid",
)


class ApplicationDefinitionStatus(models.TextChoices):
    """Enumerate supported application definition status values."""

    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    RETIRED = "retired", "Retired"


class ApplicationTargetKind(models.TextChoices):
    """Enumerate supported application target kind values."""

    MERCH_SUBMISSION = "merch_submission", "Merchandise submission"
    DJ_SET = "dj_set", "DJ set"
    FURSUIT_DANCE_COMPETITION = "fursuit_dance_competition", "Fursuit Dance Competition"
    MAID_CAFE = "maid_cafe", "Maid Cafe"
    ADULT_FURSUIT_STRIPTEASE = "adult_fursuit_striptease", "Adult Fursuit Striptease"
    VOLUNTEER = "volunteer", "Volunteer"
    FEEDBACK = "feedback", "Feedback"
    IDEA = "idea", "Idea"
    DAMAGE_REPORT = "damage_report", "SecOps damage report"
    HELPER = "helper", "Time-bounded helper"
    PROGRAMME_ITEM = "programme_item", "Programme item"


class ProgrammeProposalState(models.TextChoices):
    """Enumerate the closed Programme proposal projection states."""

    DRAFT = "draft", "Draft"
    SEALED = "sealed", "Sealed"
    SUBMITTED = "submitted", "Submitted"
    WITHDRAWN = "withdrawn", "Withdrawn"


class ProgrammeCollaboratorState(models.TextChoices):
    """Enumerate persisted collaborator states; expiry remains derived."""

    INVITED = "invited", "Invited"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"
    LEFT = "left", "Left"
    REMOVED = "removed", "Removed"


class ProgrammeContributorRole(models.TextChoices):
    """Enumerate immutable proposal-revision contributor roles."""

    LEAD = "lead", "Lead"
    COLLABORATOR = "collaborator", "Collaborator"


class ProgrammeContributorRequirement(models.TextChoices):
    """Enumerate per-role contributor profile requirements."""

    HIDDEN = "hidden", "Hidden"
    OPTIONAL = "optional", "Optional"
    REQUIRED = "required", "Required"


class ProgrammeContributorFieldCode(models.TextChoices):
    """Enumerate the fixed public contributor-profile fields."""

    PUBLIC_NAME = "public_name", "Public name"
    BIOGRAPHY = "biography", "Biography"
    PRONOUNS = "pronouns", "Pronouns"
    WEBSITE = "website", "Website"


class ProgrammeRevisionResponseKind(models.TextChoices):
    """Enumerate collaborator responses to an exact sealed revision."""

    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    DECLINED = "declined", "Declined"


class ProgrammeCommandAggregateKind(models.TextChoices):
    """Enumerate Programme command aggregate roots."""

    CALL = "call", "Call"
    PROPOSAL = "proposal", "Proposal"


class ProgrammeCommandAction(models.TextChoices):
    """Enumerate the closed Applications-owned Programme command surface."""

    CALL_CREATED = "call_created", "Call created"
    CALL_CONFIGURED = "call_configured", "Call configured"
    CALL_ACTIVATED = "call_activated", "Call activated"
    CALL_RETIRED = "call_retired", "Call retired"
    CALL_SUCCESSOR_CREATED = "call_successor_created", "Call successor created"
    PROPOSAL_STARTED = "proposal_started", "Proposal started"
    PROPOSAL_SELECTION_REVISED = (
        "proposal_selection_revised",
        "Proposal selection revised",
    )
    PROPOSAL_ANSWER_REVISED = "proposal_answer_revised", "Proposal answer revised"
    COLLABORATOR_INVITED = "collaborator_invited", "Collaborator invited"
    COLLABORATOR_ACCEPTED = "collaborator_accepted", "Collaborator accepted"
    COLLABORATOR_DECLINED = "collaborator_declined", "Collaborator declined"
    COLLABORATOR_LEFT = "collaborator_left", "Collaborator left"
    COLLABORATOR_REMOVED = "collaborator_removed", "Collaborator removed"
    COLLABORATOR_REINVITED = "collaborator_reinvited", "Collaborator reinvited"
    CONTRIBUTOR_PROFILE_REVISED = (
        "contributor_profile_revised",
        "Contributor profile revised",
    )
    PROPOSAL_SEALED = "proposal_sealed", "Proposal sealed"
    PROPOSAL_REOPENED = "proposal_reopened", "Proposal reopened"
    REVISION_ACKNOWLEDGED = "revision_acknowledged", "Revision acknowledged"
    REVISION_DECLINED = "revision_declined", "Revision declined"
    PROPOSAL_SUBMITTED = "proposal_submitted", "Proposal submitted"
    PROPOSAL_WITHDRAWN = "proposal_withdrawn", "Proposal withdrawn"


class ProgrammeCommandResultKind(models.TextChoices):
    """Enumerate target kinds returned by Programme commands."""

    CALL = "call", "Call"
    TRACK = "track", "Track"
    FORMAT = "format", "Format"
    CONTRIBUTOR_FIELD = "contributor_field", "Contributor field"
    PROPOSAL = "proposal", "Proposal"
    SELECTION_REVISION = "selection_revision", "Selection revision"
    ANSWER_REVISION = "answer_revision", "Answer revision"
    COLLABORATOR = "collaborator", "Collaborator"
    COLLABORATOR_TRANSITION = "collaborator_transition", "Collaborator transition"
    PROFILE_REVISION = "profile_revision", "Profile revision"
    PROPOSAL_REVISION = "proposal_revision", "Proposal revision"
    REVISION_RESPONSE = "revision_response", "Revision response"


class ProgrammeImportBatchState(models.TextChoices):
    """Enumerate the closed Programme-import batch lifecycle."""

    STAGED = "staged", "Staged"
    DISCARDED = "discarded", "Discarded"


class ProgrammeImportItemKind(models.TextChoices):
    """Enumerate supported Programme-import item discriminators."""

    CALL = "call", "Call"
    PROPOSAL = "proposal", "Proposal"


class ProgrammeImportItemState(models.TextChoices):
    """Enumerate the closed Programme-import item lifecycle."""

    STAGED = "staged", "Staged"
    APPLIED = "applied", "Applied"
    DISCARDED = "discarded", "Discarded"


class ProgrammeImportPreviewStatus(models.TextChoices):
    """Enumerate sanitized outcomes for an exact preview item."""

    READY = "ready", "Ready"
    BLOCKED = "blocked", "Blocked"
    NO_OP = "no_op", "No operation"
    CONFLICT = "conflict", "Conflict"


class ProgrammeImportPreviewAction(models.TextChoices):
    """Enumerate the only actions a preview can authorize."""

    COMMIT_CALL = "commit_call", "Commit call"
    CLAIM_PROPOSAL = "claim_proposal", "Claim proposal"
    NONE = "none", "None"


class ProgrammeImportDependencyState(models.TextChoices):
    """Enumerate imported-proposal dependency observations."""

    NONE = "none", "None"
    MISSING = "missing", "Missing"
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    RETIRED = "retired", "Retired"


class ProgrammeImportAggregateKind(models.TextChoices):
    """Enumerate Programme-import command aggregate roots."""

    BATCH = "batch", "Batch"
    PREVIEW = "preview", "Preview"
    ITEM = "item", "Item"


class ProgrammeImportCommandAction(models.TextChoices):
    """Enumerate the closed Programme-import command surface."""

    BATCH_STAGED = "batch_staged", "Batch staged"
    BATCH_PREVIEWED = "batch_previewed", "Batch previewed"
    CALL_COMMITTED = "call_committed", "Call committed"
    PROPOSAL_CLAIMED = "proposal_claimed", "Proposal claimed"
    BATCH_DISCARDED = "batch_discarded", "Batch discarded"


class ProgrammeImportCommandResultKind(models.TextChoices):
    """Enumerate targets returned by Programme-import commands."""

    BATCH = "batch", "Batch"
    PREVIEW = "preview", "Preview"
    CALL_BINDING = "call_binding", "Call binding"
    PROPOSAL_BINDING = "proposal_binding", "Proposal binding"
    DISCARD = "discard", "Discard"


class _ClosedProgrammeApplicationModel(UUIDTimeStampedModel):
    """Reject Programme-call ORM writes outside registered commands."""

    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True

    @override
    def full_clean(
        self,
        exclude: Iterable[str] | None = None,
        validate_unique: bool = True,
        validate_constraints: bool = True,
    ) -> None:
        """Validate owned fields without querying external owner models.

        Parameters
        ----------
        exclude : Iterable[str] | None, default=None
            Field names Django should omit from validation.
        validate_unique : bool, default=True
            Whether Django should evaluate uniqueness constraints.
        validate_constraints : bool, default=True
            Whether Django should evaluate model constraints.
        """
        excluded_fields = set(exclude or ())
        excluded_fields.update(
            {
                "account",
                "actor",
                "created_by",
                "edition",
                "organization",
                "owner_department",
            }
        )
        super().full_clean(
            exclude=excluded_fields,
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist through the closed Programme writer.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's model save operation.
        **kwargs : Any
            Keyword arguments forwarded to Django's model save operation.
        """
        require_programme_application_writer()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Permit current-record replacement only through the closed writer.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's model delete operation.
        **kwargs : Any
            Keyword arguments forwarded to Django's model delete operation.

        Returns
        -------
        tuple[int, dict[str, int]]
            Django's deleted-object count and per-model count mapping.
        """
        require_programme_application_writer()
        return super().delete(*args, **kwargs)


class _AppendOnlyProgrammeApplicationModel(_ClosedProgrammeApplicationModel):
    """Reject updates to retained Programme-call history and receipts."""

    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert one immutable evidence row and reject later updates.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded for an allowed initial insert.
        **kwargs : Any
            Keyword arguments forwarded for an allowed initial insert.

        Raises
        ------
        ValidationError
            If an existing immutable evidence row would be updated.
        """
        if not self._state.adding:
            raise ValidationError(
                "Programme application evidence is append-only.",
                code="immutable_programme_application_evidence",
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Reject deletion of immutable Programme-call evidence.

        Parameters
        ----------
        *args : Any
            Positional deletion arguments rejected with the operation.
        **kwargs : Any
            Keyword deletion arguments rejected with the operation.

        Returns
        -------
        tuple[int, dict[str, int]]
            This method never returns because retained evidence cannot be deleted.

        Raises
        ------
        ValidationError
            Always, because Programme evidence is append-only.
        """
        del args, kwargs
        raise ValidationError(
            "Programme application evidence is retained.",
            code="protected_programme_application_evidence",
        )


class _ClosedProgrammeImportModel(UUIDTimeStampedModel):
    """Reject Programme-import ORM writes outside its dedicated writer."""

    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True

    @override
    def full_clean(
        self,
        exclude: Iterable[str] | None = None,
        validate_unique: bool = True,
        validate_constraints: bool = True,
    ) -> None:
        """Validate import-owned fields without querying owner modules.

        Parameters
        ----------
        exclude : Iterable[str] | None, default=None
            Field names Django should omit from validation.
        validate_unique : bool, default=True
            Whether Django should evaluate uniqueness constraints.
        validate_constraints : bool, default=True
            Whether Django should evaluate model constraints.
        """
        excluded_fields = set(exclude or ())
        excluded_fields.update(
            {
                "actor",
                "created_by",
                "discarded_by",
                "edition",
                "organization",
                "owner_department",
                "staged_by",
            }
        )
        super().full_clean(
            exclude=excluded_fields,
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist through the closed import writer.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's model save operation.
        **kwargs : Any
            Keyword arguments forwarded to Django's model save operation.
        """
        require_programme_import_writer()
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Permit current-record deletion only inside the import writer.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's model delete operation.
        **kwargs : Any
            Keyword arguments forwarded to Django's model delete operation.

        Returns
        -------
        tuple[int, dict[str, int]]
            Django's deleted-object count and per-model count mapping.
        """
        require_programme_import_writer()
        return super().delete(*args, **kwargs)


class _AppendOnlyProgrammeImportModel(_ClosedProgrammeImportModel):
    """Reject updates and deletes of retained Programme-import evidence."""

    class Meta:
        """Configure Django's declarative class metadata."""

        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert immutable import evidence and reject subsequent updates.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded for an allowed initial insert.
        **kwargs : Any
            Keyword arguments forwarded for an allowed initial insert.

        Raises
        ------
        ValidationError
            If an existing immutable evidence row would be updated.
        """
        if not self._state.adding:
            raise ValidationError(
                "Programme import evidence is append-only.",
                code="immutable_programme_import_evidence",
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Reject deletion of retained Programme-import evidence.

        Parameters
        ----------
        *args : Any
            Positional deletion arguments rejected with the operation.
        **kwargs : Any
            Keyword deletion arguments rejected with the operation.

        Returns
        -------
        tuple[int, dict[str, int]]
            This method never returns because retained evidence cannot be deleted.

        Raises
        ------
        ValidationError
            Always, because Programme-import evidence is append-only.
        """
        del args, kwargs
        raise ValidationError(
            "Programme import evidence is retained.",
            code="protected_programme_import_evidence",
        )


class ApplicationClassification(models.TextChoices):
    """Enumerate supported application classification values."""

    INTERNAL = "C1", "Internal"
    PERSONAL = "C2", "Personal"
    RESTRICTED = "C3", "Restricted"
    SECURITY_CRITICAL = "C4", "Security critical"


class ApplicationEligibilityKind(models.TextChoices):
    """Enumerate supported application eligibility kind values."""

    AUTHENTICATED_PERSON = "authenticated_person", "Authenticated person"
    EDITION_PARTICIPANT = "edition_participant", "Edition participant"
    REGISTERED_ATTENDEE = "registered_attendee", "Registered attendee"
    CONFIRMED_ATTENDEE = "confirmed_attendee", "Confirmed attendee"
    ACTIVE_VOLUNTEER = "active_volunteer", "Active volunteer"


class ApplicationQuestionType(models.TextChoices):
    """Enumerate supported application question type values."""

    SHORT_TEXT = "short_text", "Short text"
    LONG_TEXT = "long_text", "Long text"
    INTEGER = "integer", "Integer"
    DECIMAL = "decimal", "Decimal"
    BOOLEAN = "boolean", "Boolean"
    SINGLE_CHOICE = "single_choice", "Single choice"
    MULTIPLE_CHOICE = "multiple_choice", "Multiple choice"
    DATE = "date", "Date"
    TIME = "time", "Time"
    INSTANT = "instant", "Date and time"
    EMAIL = "email", "Email"
    PHONE = "phone", "Phone"
    URL = "url", "URL"
    ADDRESS = "address", "Address"
    PERSON_REFERENCE = "person_reference", "Person reference"
    DOMAIN_REFERENCE = "domain_reference", "Domain reference"
    SAFE_FILE = "safe_file", "Safety-checked file"


class ApplicationSourceBinding(models.TextChoices):
    """Enumerate supported application source binding values."""

    NONE = "", "No automatic source"
    ACCOUNT_DISPLAY_NAME = "account.display_name", "Account display name"
    REGISTRATION_TELEGRAM = "registration.telegram", "Registration Telegram contact"


class ApplicationState(models.TextChoices):
    """Enumerate supported application state values."""

    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    UNDER_REVIEW = "under_review", "Under review"
    CHANGES_REQUESTED = "changes_requested", "Changes requested"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"


class AnswerSource(models.TextChoices):
    """Enumerate supported answer source values."""

    APPLICANT = "applicant", "Applicant"
    STAFF_CORRECTION = "staff_correction", "Staff correction"
    SYSTEM_SOURCE = "system_source", "Authoritative source binding"


class ReviewDecisionKind(models.TextChoices):
    """Enumerate supported review decision kind values."""

    START_REVIEW = "start_review", "Start review"
    REQUEST_CHANGES = "request_changes", "Request changes"
    ACCEPT = "accept", "Accept"
    REJECT = "reject", "Reject"


class ReviewerBasis(models.TextChoices):
    """Enumerate supported reviewer basis values."""

    IMMUTABLE_ROLE = "immutable_role", "Immutable role version"
    NAMED_PERSON = "named_person", "Named person"


class ApplicationDefinition(UUIDTimeStampedModel):
    """One immutable-on-activation edition definition version."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="application_definitions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="application_definitions",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    version = models.PositiveIntegerField()
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    status = models.CharField(
        max_length=16,
        choices=ApplicationDefinitionStatus,
        default=ApplicationDefinitionStatus.DRAFT,
    )
    target_adapter_kind = models.CharField(max_length=48, choices=ApplicationTargetKind)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, max_length=4_000)
    purpose = models.CharField(max_length=500)
    classification = models.CharField(
        max_length=2,
        choices=ApplicationClassification,
        default=ApplicationClassification.PERSONAL,
    )
    eligibility_kind = models.CharField(
        max_length=32,
        choices=ApplicationEligibilityKind,
        default=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
    )
    max_submissions_per_person = models.PositiveSmallIntegerField(
        default=1,
        validators=(
            MinValueValidator(1),
            MaxValueValidator(MAX_DEFINITION_CARDINALITY),
        ),
    )
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    applicant_edit_until = models.DateTimeField()
    minimum_age = models.PositiveSmallIntegerField(
        default=0, validators=(MaxValueValidator(120),)
    )
    audience_policy_code = models.CharField(
        max_length=120, blank=True, validators=(POLICY_CODE_VALIDATOR,)
    )
    retention_policy_code = models.CharField(
        max_length=120, blank=True, validators=(POLICY_CODE_VALIDATOR,)
    )
    age_policy_code = models.CharField(
        max_length=120, blank=True, validators=(POLICY_CODE_VALIDATOR,)
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_definitions_created",
    )
    activated_at = models.DateTimeField(null=True, blank=True, editable=False)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="application_definitions_activated",
    )
    retired_at = models.DateTimeField(null=True, blank=True, editable=False)
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="application_definitions_retired",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "code", "-version", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "code", "version"),
                name="applications_definition_version_unique",
            ),
            models.UniqueConstraint(
                fields=("edition", "code"),
                condition=Q(status=ApplicationDefinitionStatus.ACTIVE),
                name="applications_definition_one_active",
            ),
            models.CheckConstraint(
                condition=Q(version__gt=0) & Q(aggregate_version__gt=0),
                name="applications_definition_versions_positive",
            ),
            models.CheckConstraint(
                condition=Q(max_submissions_per_person__gte=1)
                & Q(max_submissions_per_person__lte=MAX_DEFINITION_CARDINALITY),
                name="applications_definition_cardinality_bounded",
            ),
            models.CheckConstraint(
                condition=Q(minimum_age__lte=120),
                name="applications_definition_age_bounded",
            ),
            models.CheckConstraint(
                condition=Q(opens_at__lt=models.F("closes_at"))
                & Q(applicant_edit_until__lte=models.F("closes_at")),
                name="applications_definition_windows_ordered",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=ApplicationDefinitionStatus.DRAFT,
                        activated_at__isnull=True,
                        activated_by__isnull=True,
                        retired_at__isnull=True,
                        retired_by__isnull=True,
                    )
                    | Q(
                        status=ApplicationDefinitionStatus.ACTIVE,
                        activated_at__isnull=False,
                        activated_by__isnull=False,
                        retired_at__isnull=True,
                        retired_by__isnull=True,
                    )
                    | Q(
                        status=ApplicationDefinitionStatus.RETIRED,
                        activated_at__isnull=False,
                        activated_by__isnull=False,
                        retired_at__isnull=False,
                        retired_by__isnull=False,
                    )
                ),
                name="applications_definition_lifecycle_evidence",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "status", "opens_at"),
                name="app_definition_scope_idx",
            )
        ]

    @property
    def is_sensitive(self) -> bool:
        """Return whether sensitive.

        Returns
        -------
        bool
            `True` when sensitive; otherwise `False`.
        """
        return self.classification in {
            ApplicationClassification.RESTRICTED,
            ApplicationClassification.SECURITY_CRITICAL,
        } or self.target_adapter_kind in {
            ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE,
            ApplicationTargetKind.DAMAGE_REPORT,
        }

    @property
    def requires_explicit_age_policy(self) -> bool:
        """Return whether the definition requires an explicit age policy.

        Returns
        -------
        bool
            `True` when the definition requires an explicit age policy; otherwise
            `False`.
        """
        return (
            self.target_adapter_kind == ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE
        )

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The application definition must match its edition.")
        if self.opens_at and self.closes_at and self.opens_at >= self.closes_at:
            raise ValidationError(
                {"closes_at": "Closing time must follow opening time."}
            )
        if (
            self.applicant_edit_until
            and self.closes_at
            and self.applicant_edit_until > self.closes_at
        ):
            raise ValidationError(
                {
                    "applicant_edit_until": "The applicant edit deadline cannot follow closing."
                }
            )
        if self.requires_explicit_age_policy and self.minimum_age < 18:
            raise ValidationError(
                {"minimum_age": "The adult application requires a minimum age of 18."},
                code="adult_application_minimum_age_required",
            )
        forbidden = {"default", "generic", "standard"}
        if self.status != ApplicationDefinitionStatus.DRAFT and (
            self.is_sensitive
            or self.target_adapter_kind
            in {
                ApplicationTargetKind.ADULT_FURSUIT_STRIPTEASE,
                ApplicationTargetKind.DAMAGE_REPORT,
            }
        ):
            if (
                not self.audience_policy_code
                or self.audience_policy_code in forbidden
                or not self.retention_policy_code
                or self.retention_policy_code in forbidden
            ):
                raise ValidationError(
                    "Restricted, adult, and case workflows require explicit versioned audience and retention policies.",
                    code="explicit_sensitive_application_policy_required",
                )
        if (
            self.status != ApplicationDefinitionStatus.DRAFT
            and self.requires_explicit_age_policy
            and (not self.age_policy_code or self.age_policy_code in forbidden)
        ):
            raise ValidationError(
                {"age_policy_code": "Choose an explicit versioned adult-age policy."},
                code="explicit_adult_age_policy_required",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        self.code = self.code.lower()
        if self.pk and not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).first()
            if (
                previous is not None
                and previous.status != ApplicationDefinitionStatus.DRAFT
            ):
                retirement_fields = {
                    "status",
                    "retired_at",
                    "retired_by_id",
                    "aggregate_version",
                    "updated_at",
                }
                changed = {
                    field.attname
                    for field in self._meta.concrete_fields
                    if getattr(previous, field.attname) != getattr(self, field.attname)
                }
                if (
                    previous.status != ApplicationDefinitionStatus.ACTIVE
                    or not changed <= retirement_fields
                ):
                    raise ValidationError(
                        "Active and retired definition versions are immutable.",
                        code="immutable_application_definition",
                    )
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationOwnerDepartment(UUIDTimeStampedModel):
    """Store application owner department records."""

    definition = models.ForeignKey(
        ApplicationDefinition,
        on_delete=models.PROTECT,
        related_name="owner_department_links",
    )
    department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="owned_application_definitions",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.UniqueConstraint(
                fields=("definition", "department"),
                name="applications_owner_department_unique",
            )
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if (
            self.definition_id
            and self.department_id
            and (
                self.department.organization_id != self.definition.organization_id
                or self.department.edition_id != self.definition.edition_id
                or self.department.retired_at is not None
            )
        ):
            raise ValidationError(
                {"department": "Choose a current Department in the same edition."}
            )
        if (
            self.definition_id
            and self.definition.status != ApplicationDefinitionStatus.DRAFT
        ):
            raise ValidationError("Owner Departments are frozen on activation.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationReviewerRole(UUIDTimeStampedModel):
    """Store application reviewer role records."""

    definition = models.ForeignKey(
        ApplicationDefinition, on_delete=models.PROTECT, related_name="reviewer_roles"
    )
    role_bundle = models.ForeignKey(
        "authorization.RoleBundle",
        on_delete=models.PROTECT,
        related_name="application_review_queues",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.UniqueConstraint(
                fields=("definition", "role_bundle"),
                name="applications_reviewer_role_unique",
            )
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.definition_id and self.role_bundle_id:
            if self.definition.status != ApplicationDefinitionStatus.DRAFT:
                raise ValidationError("Reviewer roles are frozen on activation.")
            if self.role_bundle.organization_id != self.definition.organization_id:
                raise ValidationError(
                    {"role_bundle": "The role belongs to another organizer."}
                )
            edition = self.definition.edition
            if not profile_allows_application_reviewer_role(
                edition.adoption_profile_code,
                edition.adoption_profile_version,
                self.role_bundle.capability_codes,
                sensitive=self.definition.is_sensitive,
            ):
                raise ValidationError(
                    {
                        "role_bundle": ValidationError(
                            (
                                "The immutable reviewer role must contain the required "
                                "review capabilities and remain wholly compatible with "
                                "this edition."
                            ),
                            code="application_reviewer_role_unavailable",
                        )
                    }
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationReviewerPerson(UUIDTimeStampedModel):
    """Store application reviewer person records."""

    definition = models.ForeignKey(
        ApplicationDefinition, on_delete=models.PROTECT, related_name="reviewer_people"
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="named_application_review_queues",
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.UniqueConstraint(
                fields=("definition", "account"),
                name="applications_reviewer_person_unique",
            )
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if (
            self.definition_id
            and self.definition.status != ApplicationDefinitionStatus.DRAFT
        ):
            raise ValidationError("Named reviewers are frozen on activation.")
        if self.account_id:
            validate_convention_subject(self.account, field_name="account")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationSection(UUIDTimeStampedModel):
    """Store application section records."""

    definition = models.ForeignKey(
        ApplicationDefinition, on_delete=models.PROTECT, related_name="sections"
    )
    key = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    title = models.CharField(max_length=160)
    help_text = models.TextField(blank=True, max_length=2_000)
    position = models.PositiveSmallIntegerField(validators=(MaxValueValidator(65_535),))

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("definition_id", "position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("definition", "key"), name="applications_section_key_unique"
            ),
            models.UniqueConstraint(
                fields=("definition", "position"),
                name="applications_section_position_unique",
            ),
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if (
            self.definition_id
            and self.definition.status != ApplicationDefinitionStatus.DRAFT
        ):
            raise ValidationError("Sections are immutable after activation.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.key = self.key.lower()
        self.full_clean()
        super().save(*args, **kwargs)


def _validate_options(field_type: str, options: object) -> None:
    if not isinstance(options, list) or len(options) > MAX_QUESTION_OPTIONS:
        raise ValidationError({"options": "Options must be a bounded list."})
    choice = field_type in {
        ApplicationQuestionType.SINGLE_CHOICE,
        ApplicationQuestionType.MULTIPLE_CHOICE,
    }
    if choice and len(options) < 2:
        raise ValidationError(
            {"options": "Choice fields require at least two options."}
        )
    if not choice and options:
        raise ValidationError({"options": "Only choice fields may define options."})
    seen: set[str] = set()
    for option in options:
        if not isinstance(option, dict) or set(option) != {"code", "label"}:
            raise ValidationError(
                {"options": "Each option requires only code and label."}
            )
        code = option.get("code")
        label = option.get("label")
        if (
            not isinstance(code, str)
            or not isinstance(label, str)
            or not code
            or len(code) > 80
            or not label.strip()
            or len(label) > 160
            or code in seen
        ):
            raise ValidationError(
                {"options": "Option codes and labels must be bounded and unique."}
            )
        seen.add(code)


class ApplicationQuestion(UUIDTimeStampedModel):
    """Store application question records."""

    definition = models.ForeignKey(
        ApplicationDefinition, on_delete=models.PROTECT, related_name="questions"
    )
    section = models.ForeignKey(
        ApplicationSection, on_delete=models.PROTECT, related_name="questions"
    )
    key = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    field_type = models.CharField(max_length=32, choices=ApplicationQuestionType)
    label = models.CharField(max_length=200)
    help_text = models.TextField(blank=True, max_length=2_000)
    position = models.PositiveSmallIntegerField(validators=(MaxValueValidator(65_535),))
    required = models.BooleanField(default=False)
    options = models.JSONField(default=list, blank=True)
    minimum_length = models.PositiveIntegerField(null=True, blank=True)
    maximum_length = models.PositiveIntegerField(null=True, blank=True)
    minimum_value = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True
    )
    maximum_value = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True
    )
    maximum_choices = models.PositiveSmallIntegerField(null=True, blank=True)
    reference_kind = models.CharField(
        max_length=80, blank=True, validators=(REFERENCE_KIND_VALIDATOR,)
    )
    source_binding = models.CharField(
        max_length=32, choices=ApplicationSourceBinding, blank=True
    )
    condition = models.JSONField(default=dict, blank=True)
    purpose = models.CharField(max_length=500)
    classification = models.CharField(max_length=2, choices=ApplicationClassification)
    applicant_visible = models.BooleanField(default=True)
    applicant_writable = models.BooleanField(default=True)
    staff_visible = models.BooleanField(default=True)
    staff_writable = models.BooleanField(default=False)
    reviewer_visible = models.BooleanField(default=True)
    public_after_approval = models.BooleanField(default=False)
    api_projection = models.BooleanField(default=True)
    retention_policy_code = models.CharField(
        max_length=120, blank=True, validators=(POLICY_CODE_VALIDATOR,)
    )

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("definition_id", "section__position", "position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("definition", "key"), name="applications_question_key_unique"
            ),
            models.UniqueConstraint(
                fields=("section", "position"),
                name="applications_question_position_unique",
            ),
            models.CheckConstraint(
                condition=Q(minimum_length__isnull=True)
                | Q(maximum_length__isnull=True)
                | Q(minimum_length__lte=models.F("maximum_length")),
                name="applications_question_length_ordered",
            ),
            models.CheckConstraint(
                condition=Q(minimum_value__isnull=True)
                | Q(maximum_value__isnull=True)
                | Q(minimum_value__lte=models.F("maximum_value")),
                name="applications_question_numeric_ordered",
            ),
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if (
            self.definition_id
            and self.definition.status != ApplicationDefinitionStatus.DRAFT
        ):
            raise ValidationError("Questions are immutable after activation.")
        if (
            self.section_id
            and self.definition_id
            and self.section.definition_id != self.definition_id
        ):
            raise ValidationError(
                {"section": "The section belongs to another definition."}
            )
        _validate_options(self.field_type, self.options)
        if (
            self.minimum_length is not None
            and self.maximum_length is not None
            and self.minimum_length > self.maximum_length
        ):
            raise ValidationError(
                {"maximum_length": "Maximum length must not be smaller."}
            )
        if (
            self.minimum_value is not None
            and self.maximum_value is not None
            and self.minimum_value > self.maximum_value
        ):
            raise ValidationError(
                {"maximum_value": "Maximum value must not be smaller."}
            )
        if self.field_type == ApplicationQuestionType.MULTIPLE_CHOICE:
            if self.maximum_choices is None or not 1 <= self.maximum_choices <= len(
                self.options
            ):
                raise ValidationError(
                    {"maximum_choices": "Choose a bound within the option set."}
                )
        elif self.maximum_choices is not None:
            raise ValidationError(
                {"maximum_choices": "Only multiple choice uses this bound."}
            )
        reference_types = {
            ApplicationQuestionType.PERSON_REFERENCE,
            ApplicationQuestionType.DOMAIN_REFERENCE,
        }
        if (self.field_type in reference_types) != bool(self.reference_kind):
            raise ValidationError(
                {"reference_kind": "Reference fields require one registered kind."}
            )
        if self.source_binding and self.applicant_writable:
            raise ValidationError(
                {"applicant_writable": "Automatically sourced values are read-only."}
            )
        if not isinstance(self.condition, dict):
            raise ValidationError({"condition": "Condition must be an object."})
        if self.condition:
            if set(self.condition) != {"question_key", "operator", "value"}:
                raise ValidationError({"condition": "Condition fields are closed."})
            if self.condition.get("operator") not in {
                "equals",
                "not_equals",
                "contains",
            }:
                raise ValidationError(
                    {"condition": "Choose a registered condition operator."}
                )
        if (
            self.definition.status != ApplicationDefinitionStatus.DRAFT
            and self.classification
            in {
                ApplicationClassification.RESTRICTED,
                ApplicationClassification.SECURITY_CRITICAL,
            }
            and not (
                self.retention_policy_code or self.definition.retention_policy_code
            )
        ):
            raise ValidationError(
                {
                    "retention_policy_code": "Sensitive fields require explicit retention."
                }
            )
        if (
            self.public_after_approval
            and self.classification != ApplicationClassification.INTERNAL
        ):
            raise ValidationError(
                {
                    "public_after_approval": "Only a separately reviewed C1 rendition may be public."
                }
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.key = self.key.lower()
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationSubmission(UUIDTimeStampedModel):
    """Store application submission records."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="application_submissions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="application_submissions",
    )
    definition = models.ForeignKey(
        ApplicationDefinition, on_delete=models.PROTECT, related_name="submissions"
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_submissions",
    )
    ordinal = models.PositiveSmallIntegerField()
    state = models.CharField(
        max_length=24, choices=ApplicationState, default=ApplicationState.DRAFT
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    submitted_at = models.DateTimeField(null=True, blank=True, editable=False)
    decided_at = models.DateTimeField(null=True, blank=True, editable=False)
    withdrawn_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("definition", "account", "ordinal"),
                name="applications_submission_ordinal_unique",
            ),
            models.CheckConstraint(
                condition=Q(ordinal__gt=0) & Q(aggregate_version__gt=0),
                name="applications_submission_versions_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        state=ApplicationState.DRAFT,
                        submitted_at__isnull=True,
                        decided_at__isnull=True,
                        withdrawn_at__isnull=True,
                    )
                    | Q(
                        state__in=(
                            ApplicationState.SUBMITTED,
                            ApplicationState.UNDER_REVIEW,
                            ApplicationState.CHANGES_REQUESTED,
                        ),
                        submitted_at__isnull=False,
                        decided_at__isnull=True,
                        withdrawn_at__isnull=True,
                    )
                    | Q(
                        state__in=(
                            ApplicationState.ACCEPTED,
                            ApplicationState.REJECTED,
                        ),
                        submitted_at__isnull=False,
                        decided_at__isnull=False,
                        withdrawn_at__isnull=True,
                    )
                    | Q(state=ApplicationState.WITHDRAWN, withdrawn_at__isnull=False)
                ),
                name="applications_submission_state_evidence",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "state", "created_at"),
                name="app_submission_queue_idx",
            ),
            models.Index(
                fields=("account", "edition", "created_at"),
                name="app_submission_owner_idx",
            ),
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.definition_id and (
            self.definition.organization_id != self.organization_id
            or self.definition.edition_id != self.edition_id
        ):
            raise ValidationError("The submission must match its definition scope.")
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The submission must match its edition scope.")
        if self.account_id:
            validate_convention_subject(self.account, field_name="account")

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.full_clean()
        super().save(*args, **kwargs)


class ApplicationFileReceipt(UUIDTimeStampedModel):
    """Trusted evidence for an object-storage upload that passed safety checks."""

    class Status(models.TextChoices):
        """Enumerate supported status values."""

        CLEAN = "clean", "Clean"
        REJECTED = "rejected", "Rejected"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="application_file_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="application_file_receipts",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_file_receipts",
    )
    status = models.CharField(max_length=16, choices=Status)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    media_type = models.CharField(max_length=120)
    storage_key = models.CharField(max_length=500)
    scanner_receipt = models.CharField(max_length=240)

    class Meta:
        """Configure Django's declarative class metadata."""

        constraints = [
            models.UniqueConstraint(
                fields=("organization", "storage_key"),
                name="applications_file_storage_key_unique",
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__gt=0)
                & ~Q(scanner_receipt="")
                & ~Q(storage_key=""),
                name="applications_file_evidence_required",
            ),
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.edition_id and self.edition.organization_id != self.organization_id:
            raise ValidationError("The file receipt must match its edition scope.")
        if self.account_id:
            validate_convention_subject(self.account, field_name="account")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValidationError({"sha256": "Use a lower-case SHA-256 digest."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if not self._state.adding:
            raise ValidationError("File safety receipts are immutable.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Delete this record when its protection rules allow it.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            The matching delete records in deterministic order.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        del args, kwargs
        raise ValidationError("File receipts require the retention workflow.")


class ApplicationAnswerRevision(UUIDTimeStampedModel):
    """Store application answer revision records."""

    submission = models.ForeignKey(
        ApplicationSubmission, on_delete=models.PROTECT, related_name="answer_revisions"
    )
    question = models.ForeignKey(
        ApplicationQuestion, on_delete=models.PROTECT, related_name="answer_revisions"
    )
    sequence = models.PositiveIntegerField()
    question_key = models.SlugField(max_length=80, editable=False)
    question_type = models.CharField(
        max_length=32, choices=ApplicationQuestionType, editable=False
    )
    classification = models.CharField(
        max_length=2, choices=ApplicationClassification, editable=False
    )
    value = models.JSONField(null=True)
    source = models.CharField(max_length=24, choices=AnswerSource)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_answer_revisions",
    )
    reason = models.CharField(max_length=240, blank=True)
    source_version = models.PositiveBigIntegerField(null=True, blank=True)
    resulting_version = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("submission_id", "question_key", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "question", "sequence"),
                name="applications_answer_sequence_unique",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0),
                name="applications_answer_sequence_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    source__in=(AnswerSource.APPLICANT, AnswerSource.SYSTEM_SOURCE),
                    reason="",
                )
                | (Q(source=AnswerSource.STAFF_CORRECTION) & ~Q(reason="")),
                name="applications_answer_staff_reason_required",
            ),
            models.CheckConstraint(
                condition=Q(
                    source_version__isnull=True,
                    resulting_version__isnull=True,
                )
                | Q(
                    source_version__gt=0,
                    resulting_version=models.F("source_version") + 1,
                ),
                name="applications_answer_version_step",
            ),
            models.UniqueConstraint(
                fields=("submission", "resulting_version"),
                condition=Q(resulting_version__isnull=False),
                name="applications_answer_result_version_uq",
            ),
        ]

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if (
            self.submission_id
            and self.question_id
            and self.question.definition_id != self.submission.definition_id
        ):
            raise ValidationError(
                {"question": "The question belongs to another definition."}
            )
        if self.question_id and (
            self.question_key != self.question.key
            or self.question_type != self.question.field_type
            or self.classification != self.question.classification
        ):
            raise ValidationError("Answer question snapshots must be authoritative.")
        if (self.source_version is None) != (self.resulting_version is None):
            raise ValidationError(
                "Answer versions must be both absent or both present.",
                code="invalid_application_answer_version_pair",
            )
        if self.source_version is not None and (
            self.source_version < 1 or self.resulting_version != self.source_version + 1
        ):
            raise ValidationError(
                "Answer versions must advance by exactly one.",
                code="invalid_application_answer_version_step",
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if not self._state.adding:
            raise ValidationError(
                "Answer revisions are append-only.", code="immutable_application_answer"
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Delete this record when its protection rules allow it.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            The matching delete records in deterministic order.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        del args, kwargs
        raise ValidationError(
            "Answer revisions are append-only.", code="protected_application_answer"
        )


class ApplicationReviewDecision(UUIDTimeStampedModel):
    """Store application review decision records."""

    submission = models.ForeignKey(
        ApplicationSubmission, on_delete=models.PROTECT, related_name="review_decisions"
    )
    sequence = models.PositiveIntegerField()
    decision = models.CharField(max_length=24, choices=ReviewDecisionKind)
    from_state = models.CharField(max_length=24, choices=ApplicationState)
    to_state = models.CharField(max_length=24, choices=ApplicationState)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_review_decisions",
    )
    reviewer_basis = models.CharField(max_length=24, choices=ReviewerBasis)
    reviewer_role_bundle = models.ForeignKey(
        "authorization.RoleBundle",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="application_review_decisions",
    )
    reason = models.CharField(max_length=500)

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("submission_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "sequence"),
                name="applications_review_sequence_unique",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0) & ~Q(reason=""),
                name="applications_review_evidence_required",
            ),
            models.CheckConstraint(
                condition=Q(
                    reviewer_basis=ReviewerBasis.IMMUTABLE_ROLE,
                    reviewer_role_bundle__isnull=False,
                )
                | Q(
                    reviewer_basis=ReviewerBasis.NAMED_PERSON,
                    reviewer_role_bundle__isnull=True,
                ),
                name="applications_review_basis_complete",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if not self._state.adding:
            raise ValidationError(
                "Review decisions are append-only.", code="immutable_application_review"
            )
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Delete this record when its protection rules allow it.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            The matching delete records in deterministic order.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        del args, kwargs
        raise ValidationError(
            "Review decisions are append-only.", code="protected_application_review"
        )


class ApplicationTargetRecord(UUIDTimeStampedModel):
    """Closed discriminated adapter receipt, never an untyped response sheet."""

    submission = models.OneToOneField(
        ApplicationSubmission, on_delete=models.PROTECT, related_name="target_record"
    )
    adapter_kind = models.CharField(max_length=48, choices=ApplicationTargetKind)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_targets_created",
    )

    def clean(self) -> None:
        """Validate and normalize the record.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        if self.adapter_kind == ApplicationTargetKind.PROGRAMME_ITEM:
            raise ValidationError(
                "Programme proposal acceptance targets require the future typed "
                "adapter.",
                code="application_target_adapter_unavailable",
            )
        if self.submission_id and (
            self.submission.state != ApplicationState.ACCEPTED
            or self.adapter_kind != self.submission.definition.target_adapter_kind
        ):
            raise ValidationError(
                "The target adapter must match one accepted application."
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if not self._state.adding:
            raise ValidationError("Typed target receipts are immutable.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Delete this record when its protection rules allow it.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            The matching delete records in deterministic order.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        del args, kwargs
        raise ValidationError("Typed target receipts are retained.")


class ApplicationCommandReceipt(UUIDTimeStampedModel):
    """Store application command receipt records."""

    class Action(models.TextChoices):
        """Enumerate supported action values."""

        DEFINITION_CREATED = "definition_created", "Definition created"
        SUCCESSOR_CREATED = "successor_created", "Successor created"
        DEFINITION_CONFIGURED = "definition_configured", "Definition configured"
        SECTION_ADDED = "section_added", "Section added"
        QUESTION_ADDED = "question_added", "Question added"
        DEFINITION_ACTIVATED = "definition_activated", "Definition activated"
        DEFINITION_RETIRED = "definition_retired", "Definition retired"
        SUBMISSION_STARTED = "submission_started", "Submission started"
        ANSWER_REVISED = "answer_revised", "Answer revised"
        APPLICATION_SUBMITTED = "application_submitted", "Application submitted"
        REVIEW_DECIDED = "review_decided", "Review decided"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="application_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="application_command_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_command_receipts",
    )
    action = models.CharField(max_length=32, choices=Action)
    retry_key = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(max_length=32)
    definition = models.ForeignKey(
        ApplicationDefinition,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    submission = models.ForeignKey(
        ApplicationSubmission,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    target_id = models.UUIDField(null=True, blank=True)
    resulting_version = models.PositiveBigIntegerField()

    class Meta:
        """Configure Django's declarative class metadata."""

        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="applications_command_retry_unique",
            ),
            models.CheckConstraint(
                condition=Q(resulting_version__gt=0) & ~Q(source_channel=""),
                name="applications_command_evidence_required",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate and persist the record.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if not self._state.adding:
            raise ValidationError("Application command receipts are append-only.")
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Delete this record when its protection rules allow it.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        tuple[int, dict[str, int]]
            The matching delete records in deterministic order.

        Raises
        ------
        ValidationError
            If the submitted state or input violates a domain invariant.
        """
        del args, kwargs
        raise ValidationError("Application command receipts are retained.")


class ProgrammeCall(_ClosedProgrammeApplicationModel):
    """Applications-owned configuration root for one versioned Programme call."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_calls",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_calls",
    )
    definition = models.OneToOneField(
        "applications.ApplicationDefinition",
        on_delete=models.PROTECT,
        related_name="programme_call",
    )
    owner_department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="programme_calls_owned",
    )
    max_collaborators = models.PositiveSmallIntegerField(
        validators=(MinValueValidator(0), MaxValueValidator(16)),
    )
    content_policy_code = models.CharField(
        max_length=120,
        validators=(POLICY_CODE_VALIDATOR,),
    )
    contributor_consent_policy_code = models.CharField(
        max_length=120,
        validators=(POLICY_CODE_VALIDATOR,),
    )
    collaboration_retention_policy_code = models.CharField(
        max_length=120,
        validators=(POLICY_CODE_VALIDATOR,),
    )

    class Meta:
        """Configure deterministic scope ordering and call bounds."""

        ordering = ("edition_id", "definition_id")
        constraints = [
            models.CheckConstraint(
                condition=Q(max_collaborators__gte=0, max_collaborators__lte=16),
                name="applications_programme_call_collaborators_valid",
            ),
            models.CheckConstraint(
                condition=~Q(content_policy_code="")
                & ~Q(contributor_consent_policy_code="")
                & ~Q(collaboration_retention_policy_code=""),
                name="applications_programme_call_policies_required",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition"),
                name="app_prg_call_scope_idx",
            )
        ]


class ProgrammeCallTrack(_ClosedProgrammeApplicationModel):
    """Closed selectable track configured for one Programme call."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_call_tracks",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_call_tracks",
    )
    call = models.ForeignKey(
        ProgrammeCall,
        on_delete=models.PROTECT,
        related_name="tracks",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    label = models.CharField(max_length=160)
    description = models.TextField(max_length=4_000, blank=True)
    position = models.PositiveSmallIntegerField()

    class Meta:
        """Configure deterministic track ordering and uniqueness."""

        ordering = ("call_id", "position", "code")
        constraints = [
            models.UniqueConstraint(
                fields=("call", "code"),
                name="applications_prg_track_code_uq",
            ),
            models.UniqueConstraint(
                fields=("call", "position"),
                name="applications_prg_track_position_uq",
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0) & ~Q(label=""),
                name="applications_prg_track_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "call", "position"),
                name="app_prg_track_scope_idx",
            )
        ]


class ProgrammeCallFormat(_ClosedProgrammeApplicationModel):
    """Closed selectable delivery format configured for one Programme call."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_call_formats",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_call_formats",
    )
    call = models.ForeignKey(
        ProgrammeCall,
        on_delete=models.PROTECT,
        related_name="formats",
    )
    code = models.SlugField(max_length=80, validators=(validate_lowercase_slug,))
    label = models.CharField(max_length=160)
    description = models.TextField(max_length=4_000, blank=True)
    position = models.PositiveSmallIntegerField()
    min_duration_minutes = models.PositiveSmallIntegerField()
    default_duration_minutes = models.PositiveSmallIntegerField()
    max_duration_minutes = models.PositiveSmallIntegerField()

    class Meta:
        """Configure deterministic format ordering and duration bounds."""

        ordering = ("call_id", "position", "code")
        constraints = [
            models.UniqueConstraint(
                fields=("call", "code"),
                name="applications_prg_format_code_uq",
            ),
            models.UniqueConstraint(
                fields=("call", "position"),
                name="applications_prg_format_position_uq",
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0)
                & ~Q(label="")
                & Q(min_duration_minutes__gt=0)
                & Q(default_duration_minutes__gte=models.F("min_duration_minutes"))
                & Q(default_duration_minutes__lte=models.F("max_duration_minutes")),
                name="applications_prg_format_duration_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "call", "position"),
                name="app_prg_format_scope_idx",
            )
        ]


class ProgrammeCallContributorField(_ClosedProgrammeApplicationModel):
    """Per-role visibility and requirement for one fixed contributor field."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_call_contributor_fields",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_call_contributor_fields",
    )
    call = models.ForeignKey(
        ProgrammeCall,
        on_delete=models.PROTECT,
        related_name="contributor_fields",
    )
    field_code = models.CharField(
        max_length=24,
        choices=ProgrammeContributorFieldCode,
    )
    lead_requirement = models.CharField(
        max_length=16,
        choices=ProgrammeContributorRequirement,
    )
    collaborator_requirement = models.CharField(
        max_length=16,
        choices=ProgrammeContributorRequirement,
    )
    position = models.PositiveSmallIntegerField()

    class Meta:
        """Configure deterministic contributor-field ordering and visibility."""

        ordering = ("call_id", "position", "field_code")
        constraints = [
            models.UniqueConstraint(
                fields=("call", "field_code"),
                name="applications_prg_contributor_field_uq",
            ),
            models.UniqueConstraint(
                fields=("call", "position"),
                name="applications_prg_contributor_position_uq",
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0)
                & ~Q(
                    lead_requirement=ProgrammeContributorRequirement.HIDDEN,
                    collaborator_requirement=ProgrammeContributorRequirement.HIDDEN,
                ),
                name="applications_prg_contributor_field_visible",
            ),
            models.CheckConstraint(
                condition=Q(field_code__in=ProgrammeContributorFieldCode.values)
                & Q(lead_requirement__in=ProgrammeContributorRequirement.values)
                & Q(
                    collaborator_requirement__in=(
                        ProgrammeContributorRequirement.values
                    )
                ),
                name="applications_prg_contributor_field_closed",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "call", "position"),
                name="app_prg_field_scope_idx",
            )
        ]


class ProgrammeProposal(_ClosedProgrammeApplicationModel):
    """Current Applications-owned projection for a collaborative proposal."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_proposals",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_proposals",
    )
    submission = models.OneToOneField(
        "applications.ApplicationSubmission",
        on_delete=models.PROTECT,
        related_name="programme_proposal",
    )
    call = models.ForeignKey(
        ProgrammeCall,
        on_delete=models.PROTECT,
        related_name="proposals",
    )
    state = models.CharField(
        max_length=16,
        choices=ProgrammeProposalState,
        default=ProgrammeProposalState.DRAFT,
    )
    sealed_revision = models.ForeignKey(
        "ProgrammeProposalRevision",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="sealed_proposal_projections",
    )
    submitted_revision = models.ForeignKey(
        "ProgrammeProposalRevision",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="submitted_proposal_projections",
    )

    class Meta:
        """Configure proposal ordering and lifecycle pointer shape."""

        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    state=ProgrammeProposalState.DRAFT,
                    sealed_revision__isnull=True,
                    submitted_revision__isnull=True,
                )
                | Q(
                    state=ProgrammeProposalState.SEALED,
                    sealed_revision__isnull=False,
                    submitted_revision__isnull=True,
                )
                | Q(
                    state=ProgrammeProposalState.SUBMITTED,
                    sealed_revision__isnull=False,
                    submitted_revision__isnull=False,
                    submitted_revision=models.F("sealed_revision"),
                )
                | Q(state=ProgrammeProposalState.WITHDRAWN),
                name="applications_prg_proposal_pointer_shape",
            ),
            models.CheckConstraint(
                condition=Q(state__in=ProgrammeProposalState.values),
                name="applications_prg_proposal_state_closed",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "state"),
                name="app_prg_proposal_scope_idx",
            )
        ]


class ProgrammeProposalSelectionRevision(_AppendOnlyProgrammeApplicationModel):
    """Append-only track and format selection for one proposal version."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_proposal_selection_revisions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_proposal_selection_revisions",
    )
    proposal = models.ForeignKey(
        ProgrammeProposal,
        on_delete=models.PROTECT,
        related_name="selection_revisions",
    )
    sequence = models.PositiveIntegerField()
    track = models.ForeignKey(
        ProgrammeCallTrack,
        on_delete=models.PROTECT,
        related_name="proposal_selection_revisions",
    )
    format = models.ForeignKey(
        ProgrammeCallFormat,
        on_delete=models.PROTECT,
        related_name="proposal_selection_revisions",
    )
    requested_duration_minutes = models.PositiveSmallIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_proposal_selection_revisions",
    )
    source_version = models.PositiveBigIntegerField()
    resulting_version = models.PositiveBigIntegerField()

    class Meta:
        """Configure deterministic selection history and version steps."""

        ordering = ("proposal_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("proposal", "sequence"),
                name="applications_prg_selection_sequence_uq",
            ),
            models.UniqueConstraint(
                fields=("proposal", "resulting_version"),
                name="applications_prg_selection_result_uq",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0)
                & Q(requested_duration_minutes__gt=0)
                & Q(source_version__gte=0)
                & Q(resulting_version=models.F("source_version") + 1),
                name="applications_prg_selection_version_step",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "proposal", "sequence"),
                name="app_prg_select_scope_idx",
            )
        ]

    def clean(self) -> None:
        """Require the requested duration to fit the selected format.

        Raises
        ------
        ValidationError
            If the requested duration falls outside the format bounds.
        """
        super().clean()
        if (
            self.format_id
            and self.requested_duration_minutes is not None
            and not (
                self.format.min_duration_minutes
                <= self.requested_duration_minutes
                <= self.format.max_duration_minutes
            )
        ):
            raise ValidationError(
                {
                    "requested_duration_minutes": ValidationError(
                        "Requested duration must fit the selected format bounds.",
                        code="invalid_programme_requested_duration",
                    )
                },
            )


class ProgrammeProposalCollaborator(_ClosedProgrammeApplicationModel):
    """Command-owned current collaborator projection; expiry is derived."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_proposal_collaborators",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_proposal_collaborators",
    )
    proposal = models.ForeignKey(
        ProgrammeProposal,
        on_delete=models.PROTECT,
        related_name="collaborators",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_proposal_collaborations",
    )
    state = models.CharField(max_length=16, choices=ProgrammeCollaboratorState)
    generation = models.PositiveIntegerField()
    invite_expires_at = models.DateTimeField()

    class Meta:
        """Configure one current collaborator projection per account."""

        ordering = ("proposal_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("proposal", "account"),
                name="applications_prg_collaborator_account_uq",
            ),
            models.CheckConstraint(
                condition=Q(generation__gt=0),
                name="applications_prg_collaborator_generation_pos",
            ),
            models.CheckConstraint(
                condition=Q(state__in=ProgrammeCollaboratorState.values),
                name="applications_prg_collaborator_state_closed",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "proposal", "state"),
                name="app_prg_collab_scope_idx",
            )
        ]


class ProgrammeProposalCollaboratorTransition(
    _AppendOnlyProgrammeApplicationModel,
):
    """Append-only collaborator invitation and membership transition."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_collaborator_transitions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_collaborator_transitions",
    )
    proposal = models.ForeignKey(
        ProgrammeProposal,
        on_delete=models.PROTECT,
        related_name="collaborator_transitions",
    )
    collaborator = models.ForeignKey(
        ProgrammeProposalCollaborator,
        on_delete=models.PROTECT,
        related_name="transitions",
    )
    sequence = models.PositiveIntegerField()
    generation = models.PositiveIntegerField()
    from_state = models.CharField(  # noqa: DJ001
        max_length=16,
        choices=ProgrammeCollaboratorState,
        null=True,
        blank=True,
    )
    to_state = models.CharField(max_length=16, choices=ProgrammeCollaboratorState)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_collaborator_transitions",
    )
    reason = models.CharField(max_length=500, blank=True)
    invite_expires_at = models.DateTimeField(null=True, blank=True)
    source_version = models.PositiveBigIntegerField()
    resulting_version = models.PositiveBigIntegerField()

    class Meta:
        """Configure deterministic collaborator history and invite shape."""

        ordering = ("collaborator_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("collaborator", "sequence"),
                name="applications_prg_collab_transition_sequence_uq",
            ),
            models.UniqueConstraint(
                fields=("proposal", "resulting_version"),
                name="applications_prg_collab_transition_result_uq",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0)
                & Q(generation__gt=0)
                & Q(source_version__gt=0)
                & Q(resulting_version=models.F("source_version") + 1),
                name="applications_prg_collab_transition_version_step",
            ),
            models.CheckConstraint(
                condition=Q(
                    to_state=ProgrammeCollaboratorState.INVITED,
                    invite_expires_at__isnull=False,
                )
                | (
                    ~Q(to_state=ProgrammeCollaboratorState.INVITED)
                    & Q(invite_expires_at__isnull=True)
                ),
                name="applications_prg_collab_transition_expiry_shape",
            ),
            models.CheckConstraint(
                condition=Q(to_state__in=ProgrammeCollaboratorState.values)
                & (
                    Q(from_state__isnull=True)
                    | Q(from_state__in=ProgrammeCollaboratorState.values)
                ),
                name="applications_prg_collab_transition_states_closed",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "proposal", "collaborator"),
                name="app_prg_collab_hist_idx",
            )
        ]


class ProgrammeProposalContributorProfileRevision(
    _AppendOnlyProgrammeApplicationModel,
):
    """Append-only proposal-local contributor profile and consent evidence."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_contributor_profile_revisions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_contributor_profile_revisions",
    )
    proposal = models.ForeignKey(
        ProgrammeProposal,
        on_delete=models.PROTECT,
        related_name="contributor_profile_revisions",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_contributor_profile_revisions",
    )
    sequence = models.PositiveIntegerField()
    predecessor = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="successors",
    )
    public_name = models.CharField(max_length=160, blank=True)
    biography = models.TextField(max_length=4_000, blank=True)
    pronouns = models.CharField(max_length=160, blank=True)
    website = models.URLField(max_length=500, blank=True)
    proposed_for_publication = models.BooleanField(default=False)
    consent_policy_code = models.CharField(
        max_length=120,
        validators=(POLICY_CODE_VALIDATOR,),
    )
    consent_acknowledged = models.BooleanField(default=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_contributor_profile_revisions_authored",
    )
    digest = models.CharField(
        max_length=64,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )
    source_version = models.PositiveBigIntegerField()
    resulting_version = models.PositiveBigIntegerField()

    class Meta:
        """Configure deterministic, non-branching profile history."""

        ordering = ("proposal_id", "account_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("proposal", "account", "sequence"),
                name="applications_prg_profile_sequence_uq",
            ),
            models.UniqueConstraint(
                fields=("proposal", "account", "digest"),
                name="applications_prg_profile_digest_uq",
            ),
            models.UniqueConstraint(
                fields=("proposal", "resulting_version"),
                name="applications_prg_profile_result_uq",
            ),
            models.UniqueConstraint(
                fields=("proposal", "account", "predecessor"),
                condition=Q(predecessor__isnull=False),
                name="applications_prg_profile_predecessor_uq",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0)
                & Q(source_version__gte=0)
                & Q(resulting_version=models.F("source_version") + 1)
                & ~Q(consent_policy_code=""),
                name="applications_prg_profile_version_step",
            ),
            models.CheckConstraint(
                condition=Q(
                    proposed_for_publication=True,
                    consent_acknowledged=True,
                )
                | Q(
                    proposed_for_publication=False,
                    public_name="",
                    biography="",
                    pronouns="",
                    website="",
                ),
                name="applications_prg_profile_public_consent",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "proposal", "account"),
                name="app_prg_profile_scope_idx",
            )
        ]

    def clean(self) -> None:
        """Reject public-copy values without explicit publication intent.

        Raises
        ------
        ValidationError
            If public profile copy is present without publication consent.
        """
        super().clean()
        if not self.proposed_for_publication and any(
            (self.public_name, self.biography, self.pronouns, self.website)
        ):
            raise ValidationError(
                "Contributor public fields require explicit publication intent.",
                code="programme_profile_publication_intent_required",
            )


class ProgrammeProposalRevision(_AppendOnlyProgrammeApplicationModel):
    """Contiguous immutable snapshot sealed for collaborator review or submit."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_proposal_revisions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_proposal_revisions",
    )
    proposal = models.ForeignKey(
        ProgrammeProposal,
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    sequence = models.PositiveIntegerField()
    predecessor = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="successors",
    )
    definition_version = models.PositiveIntegerField()
    selection_revision = models.ForeignKey(
        ProgrammeProposalSelectionRevision,
        on_delete=models.PROTECT,
        related_name="sealed_proposal_revisions",
    )
    source_version = models.PositiveBigIntegerField()
    resulting_version = models.PositiveBigIntegerField()
    digest = models.CharField(
        max_length=64,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_proposal_revisions_created",
    )
    sealed_at = models.DateTimeField()

    class Meta:
        """Configure deterministic, non-branching proposal revision history."""

        ordering = ("proposal_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("proposal", "sequence"),
                name="applications_prg_revision_sequence_uq",
            ),
            models.UniqueConstraint(
                fields=("proposal", "digest"),
                name="applications_prg_revision_digest_uq",
            ),
            models.UniqueConstraint(
                fields=("proposal", "resulting_version"),
                name="applications_prg_revision_result_uq",
            ),
            models.UniqueConstraint(
                fields=("proposal", "predecessor"),
                condition=Q(predecessor__isnull=False),
                name="applications_prg_revision_predecessor_uq",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0)
                & Q(definition_version__gt=0)
                & Q(source_version__gt=0)
                & Q(resulting_version=models.F("source_version") + 1),
                name="applications_prg_revision_version_step",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "proposal", "sequence"),
                name="app_prg_revision_scope_idx",
            )
        ]


class ProgrammeProposalRevisionAnswer(_AppendOnlyProgrammeApplicationModel):
    """One explicit applicable-question row in an immutable proposal revision."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_answers",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_answers",
    )
    revision = models.ForeignKey(
        ProgrammeProposalRevision,
        on_delete=models.PROTECT,
        related_name="answers",
    )
    question = models.ForeignKey(
        "applications.ApplicationQuestion",
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_answers",
    )
    answer_revision = models.ForeignKey(
        ApplicationAnswerRevision,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_answers",
    )
    question_key = models.SlugField(max_length=80, editable=False)
    question_type = models.CharField(
        max_length=32,
        choices=ApplicationQuestionType,
        editable=False,
    )
    classification = models.CharField(
        max_length=2,
        choices=ApplicationClassification,
        editable=False,
    )

    class Meta:
        """Configure one answer snapshot per applicable question."""

        ordering = ("revision_id", "question_key", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("revision", "question"),
                name="applications_prg_revision_answer_question_uq",
            ),
            models.UniqueConstraint(
                fields=("revision", "question_key"),
                name="applications_prg_revision_answer_key_uq",
            ),
            models.CheckConstraint(
                condition=Q(question_type__in=ApplicationQuestionType.values)
                & Q(classification__in=ApplicationClassification.values),
                name="applications_prg_revision_answer_catalogs_closed",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "revision"),
                name="app_prg_answer_scope_idx",
            )
        ]


class ProgrammeProposalRevisionContributor(_AppendOnlyProgrammeApplicationModel):
    """Immutable lead or accepted collaborator snapshot for one revision."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_contributors",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_contributors",
    )
    revision = models.ForeignKey(
        ProgrammeProposalRevision,
        on_delete=models.PROTECT,
        related_name="contributors",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_contributions",
    )
    role = models.CharField(max_length=16, choices=ProgrammeContributorRole)
    accepted_transition = models.ForeignKey(
        ProgrammeProposalCollaboratorTransition,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revision_contributors",
    )
    profile_revision = models.ForeignKey(
        ProgrammeProposalContributorProfileRevision,
        on_delete=models.PROTECT,
        related_name="revision_contributors",
    )

    class Meta:
        """Configure one contributor per revision and exactly one lead slot."""

        ordering = ("revision_id", "role", "account_id")
        constraints = [
            models.UniqueConstraint(
                fields=("revision", "account"),
                name="applications_prg_revision_contributor_uq",
            ),
            models.UniqueConstraint(
                fields=("revision",),
                condition=Q(role=ProgrammeContributorRole.LEAD),
                name="applications_prg_revision_one_lead_uq",
            ),
            models.CheckConstraint(
                condition=Q(
                    role=ProgrammeContributorRole.LEAD,
                    accepted_transition__isnull=True,
                )
                | Q(
                    role=ProgrammeContributorRole.COLLABORATOR,
                    accepted_transition__isnull=False,
                ),
                name="applications_prg_revision_contributor_role_shape",
            ),
            models.CheckConstraint(
                condition=Q(role__in=ProgrammeContributorRole.values),
                name="applications_prg_revision_contributor_role_closed",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "revision", "role"),
                name="app_prg_rev_contrib_idx",
            )
        ]


class ProgrammeProposalRevisionResponse(_AppendOnlyProgrammeApplicationModel):
    """Append-only collaborator response to one exact proposal revision."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_responses",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_responses",
    )
    revision = models.ForeignKey(
        ProgrammeProposalRevision,
        on_delete=models.PROTECT,
        related_name="responses",
    )
    contributor = models.ForeignKey(
        ProgrammeProposalRevisionContributor,
        on_delete=models.PROTECT,
        related_name="responses",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_responses",
    )
    response = models.CharField(max_length=16, choices=ProgrammeRevisionResponseKind)
    profile_revision = models.ForeignKey(
        ProgrammeProposalContributorProfileRevision,
        on_delete=models.PROTECT,
        related_name="revision_responses",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_proposal_revision_responses_authored",
    )
    source_version = models.PositiveBigIntegerField()
    resulting_version = models.PositiveBigIntegerField()
    responded_at = models.DateTimeField()

    class Meta:
        """Configure one immutable response per collaborator and revision."""

        ordering = ("revision_id", "responded_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("revision", "contributor"),
                name="applications_prg_revision_response_uq",
            ),
            models.UniqueConstraint(
                fields=("revision", "resulting_version"),
                name="applications_prg_response_result_uq",
            ),
            models.CheckConstraint(
                condition=Q(source_version__gt=0)
                & Q(resulting_version=models.F("source_version") + 1),
                name="applications_prg_response_version_step",
            ),
            models.CheckConstraint(
                condition=Q(response__in=ProgrammeRevisionResponseKind.values),
                name="applications_prg_response_closed",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "revision", "response"),
                name="app_prg_response_scope_idx",
            )
        ]


class ProgrammeCommandReceipt(_AppendOnlyProgrammeApplicationModel):
    """Retained Applications-owned idempotency and Programme command evidence."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_application_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_application_command_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_application_command_receipts",
    )
    aggregate_kind = models.CharField(
        max_length=16,
        choices=ProgrammeCommandAggregateKind,
    )
    action = models.CharField(max_length=32, choices=ProgrammeCommandAction)
    retry_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )
    reason = models.CharField(max_length=500, blank=True)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(
        max_length=32,
        validators=(PROGRAMME_SOURCE_CHANNEL_VALIDATOR,),
    )
    definition = models.ForeignKey(
        "applications.ApplicationDefinition",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="programme_command_receipts",
    )
    submission = models.ForeignKey(
        "applications.ApplicationSubmission",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="programme_command_receipts",
    )
    target_id = models.UUIDField()
    result_kind = models.CharField(
        max_length=32,
        choices=ProgrammeCommandResultKind,
    )
    expected_version = models.PositiveBigIntegerField()
    resulting_version = models.PositiveBigIntegerField()

    class Meta:
        """Configure scope-bound idempotency and aggregate evidence shape."""

        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="applications_prg_command_retry_uq",
            ),
            models.UniqueConstraint(
                fields=("definition", "resulting_version"),
                condition=Q(definition__isnull=False, submission__isnull=True),
                name="applications_prg_call_command_result_uq",
            ),
            models.UniqueConstraint(
                fields=("submission", "resulting_version"),
                condition=Q(submission__isnull=False),
                name="applications_prg_proposal_command_result_uq",
            ),
            models.CheckConstraint(
                condition=Q(expected_version__gte=0)
                & Q(resulting_version=models.F("expected_version") + 1)
                & ~Q(source_channel=""),
                name="applications_prg_command_version_step",
            ),
            models.CheckConstraint(
                condition=Q(
                    aggregate_kind=ProgrammeCommandAggregateKind.CALL,
                    definition__isnull=False,
                    submission__isnull=True,
                )
                | Q(
                    aggregate_kind=ProgrammeCommandAggregateKind.PROPOSAL,
                    definition__isnull=False,
                    submission__isnull=False,
                ),
                name="applications_prg_command_aggregate_shape",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_kind__in=ProgrammeCommandAggregateKind.values)
                & Q(action__in=ProgrammeCommandAction.values)
                & Q(result_kind__in=ProgrammeCommandResultKind.values),
                name="applications_prg_command_catalogs_closed",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "action", "created_at"),
                name="app_prg_command_scope_idx",
            )
        ]

    def clean(self) -> None:
        """Validate the local aggregate shape and exact version step.

        Raises
        ------
        ValidationError
            If aggregate references or optimistic versions are inconsistent.
        """
        super().clean()
        if (
            self.expected_version is not None
            and self.resulting_version is not None
            and (
                self.expected_version < 0
                or self.resulting_version != self.expected_version + 1
            )
        ):
            raise ValidationError(
                "Programme command versions must advance by exactly one.",
                code="invalid_programme_command_version_step",
            )
        if self.aggregate_kind == ProgrammeCommandAggregateKind.CALL:
            valid_shape = self.definition_id is not None and self.submission_id is None
        elif self.aggregate_kind == ProgrammeCommandAggregateKind.PROPOSAL:
            valid_shape = (
                self.definition_id is not None and self.submission_id is not None
            )
        else:
            valid_shape = False
        if not valid_shape:
            raise ValidationError(
                "Programme command aggregate references do not match its kind.",
                code="invalid_programme_command_aggregate_shape",
            )


class ProgrammeImportBatch(_ClosedProgrammeImportModel):
    """Current, privacy-bounded staging root for one Programme import."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_import_batches",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_import_batches",
    )
    owner_department = models.ForeignKey(
        "workforce.Department",
        on_delete=models.PROTECT,
        related_name="programme_import_batches_owned",
    )
    source_system = models.CharField(
        max_length=80,
        validators=(PROGRAMME_IMPORT_SOURCE_SYSTEM_VALIDATOR,),
    )
    schema_version = models.PositiveSmallIntegerField(default=1, editable=False)
    source_digest = models.CharField(
        max_length=64,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )
    item_count = models.PositiveIntegerField(
        validators=(MinValueValidator(1), MaxValueValidator(1_000)),
    )
    retention_policy_code = models.CharField(
        max_length=120,
        validators=(POLICY_CODE_VALIDATOR,),
    )
    expires_at = models.DateTimeField()
    state = models.CharField(
        max_length=16,
        choices=ProgrammeImportBatchState,
        default=ProgrammeImportBatchState.STAGED,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    staged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_import_batches_staged",
    )
    discarded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="programme_import_batches_discarded",
    )
    discarded_at = models.DateTimeField(null=True, blank=True, editable=False)
    discard_reason = models.CharField(max_length=500, blank=True, editable=False)

    class Meta:
        """Configure exact scope, lifecycle shape, expiry, and queries."""

        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(schema_version=1)
                & Q(item_count__gte=1, item_count__lte=1_000)
                & Q(aggregate_version__gt=0)
                & ~Q(source_system="")
                & ~Q(retention_policy_code="")
                & Q(expires_at__gt=models.F("created_at")),
                name="applications_prg_imp_batch_bounds",
            ),
            models.CheckConstraint(
                condition=Q(
                    state=ProgrammeImportBatchState.STAGED,
                    aggregate_version=1,
                    discarded_by__isnull=True,
                    discarded_at__isnull=True,
                    discard_reason="",
                )
                | (
                    Q(
                        state=ProgrammeImportBatchState.DISCARDED,
                        aggregate_version=2,
                        discarded_by__isnull=False,
                        discarded_at__isnull=False,
                    )
                    & ~Q(discard_reason="")
                ),
                name="applications_prg_imp_batch_state",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "owner_department", "state"),
                name="app_prg_imp_batch_scope_idx",
            ),
            models.Index(
                fields=("state", "expires_at"),
                name="app_prg_imp_batch_expiry_idx",
            ),
        ]


class ProgrammeImportItem(_ClosedProgrammeImportModel):
    """Current staged import item whose private payload is later cleared."""

    batch = models.ForeignKey(
        ProgrammeImportBatch,
        on_delete=models.PROTECT,
        related_name="items",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_import_items",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_import_items",
    )
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=8, choices=ProgrammeImportItemKind)
    source_key = models.CharField(
        max_length=200,
        validators=(PROGRAMME_IMPORT_SOURCE_KEY_VALIDATOR,),
    )
    source_digest = models.CharField(
        max_length=64,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )
    canonical_payload = models.BinaryField(null=True, blank=True, editable=False)
    payload_size_bytes = models.PositiveIntegerField()
    dependency_source_system = models.CharField(
        max_length=80,
        blank=True,
        validators=(PROGRAMME_IMPORT_SOURCE_SYSTEM_VALIDATOR,),
    )
    dependency_source_key = models.CharField(
        max_length=200,
        blank=True,
        validators=(PROGRAMME_IMPORT_SOURCE_KEY_VALIDATOR,),
    )
    state = models.CharField(
        max_length=16,
        choices=ProgrammeImportItemState,
        default=ProgrammeImportItemState.STAGED,
    )
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)

    class Meta:
        """Configure item order, source identity, dependency, and scrub shape."""

        ordering = ("batch_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "sequence"),
                name="applications_prg_imp_item_sequence_uq",
            ),
            models.UniqueConstraint(
                fields=("batch", "kind", "source_key"),
                name="applications_prg_imp_item_source_uq",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0)
                & Q(payload_size_bytes__gt=0)
                & ~Q(source_key=""),
                name="applications_prg_imp_item_bounds",
            ),
            models.CheckConstraint(
                condition=Q(
                    kind=ProgrammeImportItemKind.CALL,
                    dependency_source_system="",
                    dependency_source_key="",
                )
                | (
                    Q(kind=ProgrammeImportItemKind.PROPOSAL)
                    & ~Q(dependency_source_system="")
                    & ~Q(dependency_source_key="")
                ),
                name="applications_prg_imp_item_dependency",
            ),
            models.CheckConstraint(
                condition=Q(
                    state=ProgrammeImportItemState.STAGED,
                    aggregate_version=1,
                    canonical_payload__isnull=False,
                )
                | Q(
                    state__in=(
                        ProgrammeImportItemState.APPLIED,
                        ProgrammeImportItemState.DISCARDED,
                    ),
                    aggregate_version=2,
                    canonical_payload__isnull=True,
                ),
                name="applications_prg_imp_item_state",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "batch", "state", "sequence"),
                name="app_prg_imp_item_scope_idx",
            ),
            models.Index(
                fields=("organization", "edition", "kind", "source_key"),
                name="app_prg_imp_item_source_idx",
            ),
        ]

    def clean(self) -> None:
        """Verify the staged canonical bytes against retained size and digest.

        Raises
        ------
        ValidationError
            If staged canonical bytes disagree with retained size or digest evidence.
        """
        super().clean()
        if self.state != ProgrammeImportItemState.STAGED:
            return
        payload = self.canonical_payload
        if payload is None:
            return
        canonical_bytes = bytes(payload)
        if len(canonical_bytes) != self.payload_size_bytes:
            raise ValidationError(
                "Programme import payload size does not match its evidence.",
                code="invalid_programme_import_payload_size",
            )
        if hashlib.sha256(canonical_bytes).hexdigest() != self.source_digest:
            raise ValidationError(
                "Programme import payload digest does not match its evidence.",
                code="invalid_programme_import_payload_digest",
            )


class ProgrammeImportPreviewRevision(_AppendOnlyProgrammeImportModel):
    """Immutable preview of an exact version-one staged import batch."""

    batch = models.ForeignKey(
        ProgrammeImportBatch,
        on_delete=models.PROTECT,
        related_name="preview_revisions",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_import_preview_revisions",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_import_preview_revisions",
    )
    revision_number = models.PositiveBigIntegerField()
    source_batch_version = models.PositiveBigIntegerField(default=1, editable=False)
    preview_digest = models.CharField(
        max_length=64,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )
    item_count = models.PositiveIntegerField(
        validators=(MinValueValidator(1), MaxValueValidator(1_000)),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_import_preview_revisions",
    )

    class Meta:
        """Configure immutable contiguous preview history."""

        ordering = ("batch_id", "revision_number", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "revision_number"),
                name="applications_prg_imp_preview_revision_uq",
            ),
            models.CheckConstraint(
                condition=Q(revision_number__gt=0)
                & Q(source_batch_version=1)
                & Q(item_count__gte=1, item_count__lte=1_000),
                name="applications_prg_imp_preview_bounds",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "batch", "revision_number"),
                name="app_prg_imp_preview_scope_idx",
            )
        ]


class ProgrammeImportPreviewItemResult(_AppendOnlyProgrammeImportModel):
    """Sanitized immutable result for one item in an exact preview."""

    preview = models.ForeignKey(
        ProgrammeImportPreviewRevision,
        on_delete=models.PROTECT,
        related_name="item_results",
    )
    item = models.ForeignKey(
        ProgrammeImportItem,
        on_delete=models.PROTECT,
        related_name="preview_results",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_import_preview_item_results",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_import_preview_item_results",
    )
    item_version = models.PositiveBigIntegerField()
    status = models.CharField(max_length=16, choices=ProgrammeImportPreviewStatus)
    action = models.CharField(max_length=16, choices=ProgrammeImportPreviewAction)
    dependency_state = models.CharField(
        max_length=8,
        choices=ProgrammeImportDependencyState,
    )
    dependency_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )
    dependency_version = models.PositiveBigIntegerField(null=True, blank=True)
    safe_field_keys = models.JSONField(blank=True)
    reason_codes = models.JSONField(blank=True)
    result_digest = models.CharField(
        max_length=64,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )

    class Meta:
        """Configure one result per item and closed preview-result shapes."""

        ordering = ("preview_id", "item_id")
        constraints = [
            models.UniqueConstraint(
                fields=("preview", "item"),
                name="applications_prg_imp_preview_item_uq",
            ),
            models.CheckConstraint(
                condition=Q(item_version__gt=0),
                name="applications_prg_imp_preview_item_version",
            ),
            models.CheckConstraint(
                condition=Q(
                    dependency_state__in=(
                        ProgrammeImportDependencyState.NONE,
                        ProgrammeImportDependencyState.MISSING,
                    ),
                    dependency_digest="",
                    dependency_version__isnull=True,
                )
                | (
                    Q(
                        dependency_state__in=(
                            ProgrammeImportDependencyState.DRAFT,
                            ProgrammeImportDependencyState.ACTIVE,
                            ProgrammeImportDependencyState.RETIRED,
                        ),
                        dependency_version__isnull=False,
                    )
                    & ~Q(dependency_digest="")
                ),
                name="applications_prg_imp_preview_dependency",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "preview", "status"),
                name="app_prg_imp_result_scope_idx",
            )
        ]

    def clean(self) -> None:
        """Require minimized preview arrays to be closed, unique, and ordered.

        Raises
        ------
        ValidationError
            If retained preview metadata is not a canonical public value list.
        """
        super().clean()
        for field_name, value, allowed in (
            ("safe_field_keys", self.safe_field_keys, PROGRAMME_IMPORT_SAFE_FIELD_KEYS),
            ("reason_codes", self.reason_codes, PROGRAMME_IMPORT_REASON_CODES),
        ):
            allowed_position = {entry: index for index, entry in enumerate(allowed)}
            if (
                not isinstance(value, list)
                or any(
                    not isinstance(entry, str) or entry not in allowed_position
                    for entry in value
                )
                or len(value) != len(set(value))
                or value != sorted(value, key=allowed_position.__getitem__)
            ):
                raise ValidationError(
                    {
                        field_name: ValidationError(
                            "Programme import preview metadata is not a closed "
                            "ordered value list.",
                            code="invalid_programme_import_preview_metadata",
                        )
                    }
                )


class ProgrammeImportSourceBinding(_AppendOnlyProgrammeImportModel):
    """Permanent source identity binding to exactly one applied target."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_import_source_bindings",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_import_source_bindings",
    )
    source_system = models.CharField(
        max_length=80,
        validators=(PROGRAMME_IMPORT_SOURCE_SYSTEM_VALIDATOR,),
    )
    kind = models.CharField(max_length=8, choices=ProgrammeImportItemKind)
    source_key = models.CharField(
        max_length=200,
        validators=(PROGRAMME_IMPORT_SOURCE_KEY_VALIDATOR,),
    )
    source_digest = models.CharField(
        max_length=64,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )
    item = models.OneToOneField(
        ProgrammeImportItem,
        on_delete=models.PROTECT,
        related_name="source_binding",
    )
    call = models.OneToOneField(
        ProgrammeCall,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="import_source_binding",
    )
    proposal = models.OneToOneField(
        ProgrammeProposal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="import_source_binding",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_import_source_bindings_created",
    )

    class Meta:
        """Configure permanent source uniqueness and exact target shape."""

        ordering = ("edition_id", "source_system", "kind", "source_key")
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "organization",
                    "edition",
                    "source_system",
                    "kind",
                    "source_key",
                ),
                name="applications_prg_imp_binding_source_uq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind=ProgrammeImportItemKind.CALL,
                        call__isnull=False,
                        proposal__isnull=True,
                    )
                    | Q(
                        kind=ProgrammeImportItemKind.PROPOSAL,
                        call__isnull=True,
                        proposal__isnull=False,
                    )
                )
                & ~Q(source_system="")
                & ~Q(source_key=""),
                name="applications_prg_imp_binding_target",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "kind", "created_at"),
                name="app_prg_imp_binding_scope_idx",
            )
        ]


class ProgrammeImportAppliedCommand(_AppendOnlyProgrammeImportModel):
    """Ordered link from an import receipt to one nested Programme command."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_import_applied_commands",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_import_applied_commands",
    )
    binding = models.ForeignKey(
        ProgrammeImportSourceBinding,
        on_delete=models.PROTECT,
        related_name="applied_commands",
    )
    import_receipt = models.ForeignKey(
        "ProgrammeImportCommandReceipt",
        on_delete=models.PROTECT,
        related_name="applied_commands",
    )
    sequence = models.PositiveIntegerField()
    programme_receipt = models.OneToOneField(
        ProgrammeCommandReceipt,
        on_delete=models.PROTECT,
        related_name="import_applied_command",
    )

    class Meta:
        """Configure exact nested-command order and one-time adoption."""

        ordering = ("import_receipt_id", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("import_receipt", "sequence"),
                name="applications_prg_imp_applied_sequence_uq",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0),
                name="applications_prg_imp_applied_sequence",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "binding", "sequence"),
                name="app_prg_imp_applied_scope_idx",
            )
        ]


class ProgrammeImportCommandReceipt(_AppendOnlyProgrammeImportModel):
    """Retained idempotency, preview-adoption, and version evidence."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="programme_import_command_receipts",
    )
    edition = models.ForeignKey(
        "events.EventEdition",
        on_delete=models.PROTECT,
        related_name="programme_import_command_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="programme_import_command_receipts",
    )
    aggregate_kind = models.CharField(
        max_length=8,
        choices=ProgrammeImportAggregateKind,
    )
    action = models.CharField(max_length=20, choices=ProgrammeImportCommandAction)
    retry_key = models.UUIDField()
    request_digest = models.CharField(
        max_length=64,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )
    reason = models.CharField(max_length=500, blank=True)
    correlation_id = models.UUIDField()
    source_channel = models.CharField(
        max_length=32,
        validators=(PROGRAMME_SOURCE_CHANNEL_VALIDATOR,),
    )
    batch = models.ForeignKey(
        ProgrammeImportBatch,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    item = models.ForeignKey(
        ProgrammeImportItem,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    preview_revision = models.ForeignKey(
        ProgrammeImportPreviewRevision,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    preview_item_result = models.ForeignKey(
        ProgrammeImportPreviewItemResult,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    source_binding = models.ForeignKey(
        ProgrammeImportSourceBinding,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="command_receipts",
    )
    adopted_preview_digest = models.CharField(
        max_length=64,
        blank=True,
        validators=(PROGRAMME_DIGEST_VALIDATOR,),
    )
    result_kind = models.CharField(
        max_length=20,
        choices=ProgrammeImportCommandResultKind,
    )
    expected_version = models.PositiveBigIntegerField()
    resulting_version = models.PositiveBigIntegerField()
    applied_command_count = models.PositiveSmallIntegerField(
        default=0,
        editable=False,
    )

    class Meta:
        """Configure shared retry identity and aggregate version uniqueness."""

        ordering = ("edition_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="applications_prg_imp_command_retry_uq",
            ),
            models.UniqueConstraint(
                fields=("batch", "aggregate_kind", "resulting_version"),
                condition=Q(item__isnull=True),
                name="applications_prg_imp_batch_result_uq",
            ),
            models.UniqueConstraint(
                fields=("item", "aggregate_kind", "resulting_version"),
                condition=Q(item__isnull=False),
                name="applications_prg_imp_item_result_uq",
            ),
            models.CheckConstraint(
                condition=Q(expected_version__gte=0)
                & Q(resulting_version=models.F("expected_version") + 1)
                & ~Q(source_channel=""),
                name="applications_prg_imp_command_version",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        action__in=(
                            ProgrammeImportCommandAction.CALL_COMMITTED,
                            ProgrammeImportCommandAction.PROPOSAL_CLAIMED,
                        ),
                        applied_command_count__gte=1,
                        applied_command_count__lte=1_001,
                    )
                    | Q(
                        action__in=(
                            ProgrammeImportCommandAction.BATCH_STAGED,
                            ProgrammeImportCommandAction.BATCH_PREVIEWED,
                            ProgrammeImportCommandAction.BATCH_DISCARDED,
                        ),
                        applied_command_count=0,
                    )
                ),
                name="applications_prg_imp_command_applied_count",
            ),
            models.CheckConstraint(
                condition=Q(
                    aggregate_kind=ProgrammeImportAggregateKind.BATCH,
                    item__isnull=True,
                )
                | Q(
                    aggregate_kind=ProgrammeImportAggregateKind.PREVIEW,
                    item__isnull=True,
                )
                | Q(
                    aggregate_kind=ProgrammeImportAggregateKind.ITEM,
                    item__isnull=False,
                ),
                name="applications_prg_imp_command_aggregate",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "edition", "action", "created_at"),
                name="app_prg_imp_command_scope_idx",
            )
        ]
