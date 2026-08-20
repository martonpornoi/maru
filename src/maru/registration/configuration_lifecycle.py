"""Page 10 registration-configuration validation, preview, review, and activation.

The legacy ``review_required`` column is retained for display compatibility while
the Page 10 writer migration is additive.  Authoritative review state is derived
from the current setup aggregate version, the exact reviewed receipt, and the
fresh configuration content digest.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Model, QuerySet
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision, decide, resolve_edition_target
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from maru.participation.models import ParticipationCapacity
from maru.registration.models import (
    MAXIMUM_PAYMENT_WINDOW_MINUTES,
    MINIMUM_PAYMENT_WINDOW_MINUTES,
    AdmissionProduct,
    ConfigurationStatus,
    MinorRegistrationPolicy,
    QuestionVisibility,
    RegistrationCommandChangeKind,
    RegistrationConfiguration,
    RegistrationProvenanceStatus,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSetupCommandReceipt,
    RegistrationSetupCommandTarget,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
    RegistrationTemplate,
    RegistrationTemplateProduct,
    RegistrationTemplateQuestion,
    RegistrationTemplateSection,
    TemplateStatus,
)
from maru.registration.question_conditions import condition_value_is_compatible
from maru.registration.services import validate_registration_answers
from maru.registration.setup_commands import (
    MAX_SETUP_PRODUCTS,
    MAX_SETUP_QUESTIONS,
    MAX_SETUP_SECTIONS,
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupCommandError,
    RegistrationSetupDependencyError,
    RegistrationSetupLifecycleConflictError,
    RegistrationSetupLimitExceededError,
    RegistrationSetupRetryConflictError,
    RegistrationSetupStateConflictError,
    RegistrationSetupVersionConflictError,
    _require_active_configuration_lifecycle_evidence,
    _require_setup_start_evidence,
)
from maru.registration.setup_content import (
    canonical_digest,
    configuration_content_digest,
    configuration_source_binding_digest,
    minor_policy_payload,
    target_content_digest,
    template_content_digest,
)
from maru.registration.setup_evidence import (
    SetupCommandTargetExpectation,
    require_setup_command_evidence_graph,
)
from maru.registration.template_lifecycle import (
    RegistrationTemplateStateConflictError,
    require_published_template_evidence,
)

if TYPE_CHECKING:
    from datetime import datetime

MAX_REVIEW_NOTE_LENGTH = 2_000
MAX_REASON_LENGTH = 240
MAX_EDITION_NAME_LENGTH = 160
MAX_SOURCE_CHANNEL_LENGTH = 32
MAX_CAPACITY_CODES = 256
MAX_QUESTION_HELP_LENGTH = 2_000
MAX_PRODUCT_DESCRIPTION_LENGTH = 2_000
MINOR_POLICY_COMMAND_TARGET_COUNT = 2
DEFAULT_ADULT_AGE = 18
_SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_EDITABLE_ORGANIZATION_LIFECYCLES = frozenset(
    {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
)
_EDITABLE_EDITION_LIFECYCLES = frozenset(
    {EventEdition.Lifecycle.DRAFT, EventEdition.Lifecycle.PREPARING}
)


class RegistrationConfigurationValidationError(RegistrationSetupCommandError):
    """A configuration is coherent enough to inspect but is not activatable."""

    reason_code = "registration_setup_validation_failed"

    def __init__(self, issues: tuple[RegistrationConfigurationIssue, ...]) -> None:
        """Initialize the RegistrationConfigurationValidationError instance.

        Parameters
        ----------
        issues : tuple[RegistrationConfigurationIssue, ...]
            The issues evaluated while registration configuration validation error.
        """
        self.issues = issues
        super().__init__("Registration configuration validation failed.")


class RegistrationConfigurationReviewRequiredError(RegistrationSetupCommandError):
    """Signal registration configuration review required."""

    reason_code = "registration_setup_review_required"


class RegistrationConfigurationActiveConflictError(RegistrationSetupCommandError):
    """Signal registration configuration active conflict."""

    reason_code = "registration_setup_active_configuration_conflict"


@dataclass(frozen=True, slots=True, order=True)
class RegistrationConfigurationIssue:
    """Describe registration configuration issue.

    Attributes
    ----------
    code
        The stable domain code to resolve or validate.
    target_kind
        The closed target kind discriminator defined by the domain catalog.
    target_key
        The stable target key used to authenticate or deduplicate the operation.
    """

    code: str
    target_kind: str
    target_key: str


@dataclass(frozen=True, slots=True)
class RegistrationPreviewSection:
    """Describe registration preview section.

    Attributes
    ----------
    key
        The lookup, signing, or idempotency key selected by the contract.
    title
        The human-readable title shown to authorized readers.
    description
        The human-readable description shown to authorized readers.
    position
        The workforce position within the exact edition structure.
    """

    key: str
    title: str
    description: str
    position: int


@dataclass(frozen=True, slots=True)
class RegistrationPreviewQuestion:
    """Describe registration preview question.

    Attributes
    ----------
    key
        The lookup, signing, or idempotency key selected by the contract.
    label
        The human-readable label shown to authorized readers.
    help_text
        The help text retained in this immutable projection.
    field_type
        The closed field type discriminator defined by the domain catalog.
    required
        The required retained in this immutable projection.
    options
        The configured option codes valid for the source question.
    purpose
        The documented purpose constraining collection and processing.
    visibility
        The closed disclosure audience applied to the projection.
    classification
        The closed sensitivity classification governing disclosure.
    condition_question_key
        The stable condition question key used to authenticate or deduplicate
        the operation.
    condition_value
        The condition value retained in this immutable projection.
    section_key
        The stable section key used to authenticate or deduplicate the
        operation.
    attendee_input
        The attendee input retained in this immutable projection.
    staff_input
        The staff input retained in this immutable projection.
    """

    key: str
    label: str
    help_text: str
    field_type: str
    required: bool
    options: tuple[str, ...]
    purpose: str
    visibility: str
    classification: str
    condition_question_key: str
    condition_value: str
    section_key: str
    attendee_input: bool
    staff_input: bool


@dataclass(frozen=True, slots=True)
class RegistrationPreviewProduct:
    """Describe registration preview product.

    Attributes
    ----------
    code
        The stable domain code to resolve or validate.
    name
        The human-readable name to normalize or persist.
    description
        The human-readable description shown to authorized readers.
    price_minor
        The price minor retained in this immutable projection.
    capacity
        The capacity retained in this immutable projection.
    entitlement_code
        The stable entitlement code from the relevant closed catalog.
    entitlement_name
        The human-readable entitlement name shown to authorized readers.
    sales_open_at
        The timezone-aware timestamp for sales open.
    sales_close_at
        The timezone-aware timestamp for sales close.
    required_capacity_codes
        The required capacity codes retained in this immutable projection.
    eligibility_explanation
        The bounded eligibility explanation retained for authorized readers.
    waitlist_enabled
        The waitlist enabled retained in this immutable projection.
    payment_window_minutes
        The payment window minutes retained in this immutable projection.
    status
        The closed status value to evaluate or expose.
    """

    code: str
    name: str
    description: str
    price_minor: int
    capacity: int
    entitlement_code: str
    entitlement_name: str
    sales_open_at: datetime | None
    sales_close_at: datetime | None
    required_capacity_codes: tuple[str, ...]
    eligibility_explanation: str
    waitlist_enabled: bool
    payment_window_minutes: int | None
    status: str


@dataclass(frozen=True, slots=True)
class RegistrationPreviewAnswerValidation:
    """Describe registration preview answer validation.

    Attributes
    ----------
    requested
        The requested retained in this immutable projection.
    valid
        The valid retained in this immutable projection.
    schema_keys
        The schema keys retained in this immutable projection.
    normalized_answer_keys
        The normalized answer keys retained in this immutable projection.
    error_fields
        The canonical error fields included in the projection or mutation.
    error_codes
        The error codes retained in this immutable projection.
    """

    requested: bool
    valid: bool | None
    schema_keys: tuple[str, ...]
    normalized_answer_keys: tuple[str, ...]
    error_fields: tuple[str, ...]
    error_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegistrationPreviewForbiddenEffects:
    """Describe registration preview forbidden effects.

    Attributes
    ----------
    account_created
        The account created retained in this immutable projection.
    registration_created
        The registration created retained in this immutable projection.
    submission_created
        The submission created retained in this immutable projection.
    reservation_created
        The reservation created retained in this immutable projection.
    waitlist_entry_created
        The waitlist entry created retained in this immutable projection.
    payment_created
        The payment created retained in this immutable projection.
    entitlement_created
        The entitlement created retained in this immutable projection.
    consent_created
        The consent created retained in this immutable projection.
    configuration_changed
        The configuration changed retained in this immutable projection.
    """

    account_created: bool = False
    registration_created: bool = False
    submission_created: bool = False
    reservation_created: bool = False
    waitlist_entry_created: bool = False
    payment_created: bool = False
    entitlement_created: bool = False
    consent_created: bool = False
    configuration_changed: bool = False


@dataclass(frozen=True, slots=True)
class RegistrationConfigurationPreview:
    """Describe registration configuration preview.

    Attributes
    ----------
    setup_id
        The setup identifier within the requested scope.
    configuration_id
        The configuration identifier within the requested scope.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    configuration_version
        The expected configuration version used to reject stale updates.
    status
        The closed status value to evaluate or expose.
    origin
        The origin retained in this immutable projection.
    content_digest
        The canonical digest used to verify content.
    source_content_digest
        The canonical digest used to verify source content.
    review_resolved
        The review resolved retained in this immutable projection.
    name
        The human-readable name to normalize or persist.
    edition_name
        The human-readable edition name shown to authorized readers.
    opens_at
        The timezone-aware timestamp for opens.
    closes_at
        The timezone-aware timestamp for closes.
    capacity
        The capacity retained in this immutable projection.
    currency
        The supported ISO 4217 currency code for monetary values.
    minimum_age
        The minimum age retained in this immutable projection.
    default_payment_window_minutes
        The default payment window minutes retained in this immutable projection.
    waitlist_enabled
        The waitlist enabled retained in this immutable projection.
    automatic_waitlist_promotion
        The automatic waitlist promotion retained in this immutable projection.
    sections
        The sections retained in this immutable projection.
    questions
        The questions retained in this immutable projection.
    products
        The products retained in this immutable projection.
    validation_issues
        The validation issues retained in this immutable projection.
    attendee_answers
        The attendee answers retained in this immutable projection.
    staff_answers
        The staff answers retained in this immutable projection.
    forbidden_effects
        The forbidden effects retained in this immutable projection.
    """

    setup_id: UUID
    configuration_id: UUID
    aggregate_version: int
    configuration_version: int
    status: str
    origin: str
    content_digest: str
    source_content_digest: str
    review_resolved: bool
    name: str
    edition_name: str
    opens_at: datetime
    closes_at: datetime
    capacity: int
    currency: str
    minimum_age: int
    default_payment_window_minutes: int
    waitlist_enabled: bool
    automatic_waitlist_promotion: bool
    sections: tuple[RegistrationPreviewSection, ...]
    questions: tuple[RegistrationPreviewQuestion, ...]
    products: tuple[RegistrationPreviewProduct, ...]
    validation_issues: tuple[RegistrationConfigurationIssue, ...]
    attendee_answers: RegistrationPreviewAnswerValidation
    staff_answers: RegistrationPreviewAnswerValidation
    forbidden_effects: RegistrationPreviewForbiddenEffects


@dataclass(frozen=True, slots=True)
class RegistrationConfigurationLifecycleResult:
    """Describe registration configuration lifecycle result.

    Attributes
    ----------
    setup_id
        The setup identifier within the requested scope.
    configuration_id
        The configuration identifier within the requested scope.
    receipt_id
        The receipt identifier within the requested scope.
    resulting_version
        The expected resulting version used to reject stale updates.
    configuration_version
        The expected configuration version used to reject stale updates.
    status
        The closed status value to evaluate or expose.
    content_digest
        The canonical digest used to verify content.
    review_resolved
        The review resolved retained in this immutable projection.
    replayed
        The replayed retained in this immutable projection.
    """

    setup_id: UUID
    configuration_id: UUID
    receipt_id: UUID
    resulting_version: int
    configuration_version: int
    status: str
    content_digest: str
    review_resolved: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class _LockedConfigurationScope:
    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    actor: Account
    control: RegistrationSetupControl
    configuration: RegistrationConfiguration
    sections: tuple[RegistrationSection, ...]
    questions: tuple[RegistrationQuestion, ...]
    products: tuple[AdmissionProduct, ...]
    minor_policy: MinorRegistrationPolicy | None
    active_capacity_codes: frozenset[str]
    decision: PolicyDecision
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class _SetupEvidenceScope:
    organization: Organization
    edition: EventEdition
    control: RegistrationSetupControl


@dataclass(frozen=True, slots=True)
class _MinorPolicyEvidenceScope:
    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    control: RegistrationSetupControl
    configuration: RegistrationConfiguration
    evaluated_at: datetime


def _field_error(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: ValidationError(message, code=code)})


def _authorize_scope(
    *,
    actor: Account,
    organization_id: object,
    series_id: object,
    edition_id: object,
    at: datetime | None = None,
) -> PolicyDecision:
    if (
        actor.pk is None
        or not isinstance(organization_id, UUID)
        or not isinstance(series_id, UUID)
        or not isinstance(edition_id, UUID)
        or not EventEdition.objects.filter(
            pk=edition_id,
            organization_id=organization_id,
            series_id=series_id,
            series__organization_id=organization_id,
        ).exists()
    ):
        raise RegistrationSetupAuthorizationDeniedError
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if target is None:
        raise RegistrationSetupAuthorizationDeniedError
    decision = decide(
        principal=actor,
        capability_code="registration.manage_configuration",
        resource=target,
        at=at,
    )
    if not decision.allowed:
        raise RegistrationSetupAuthorizationDeniedError
    return decision


def _strict_uuid(value: object, *, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise _field_error(
            field,
            "Enter a valid UUID.",
            "registration_setup_uuid_invalid",
        )
    return value


def _expected_version(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise _field_error(
            "expected_version",
            "Enter the current positive registration setup version.",
            "registration_setup_expected_version_invalid",
        )
    return value


def _normalized_text(
    value: object,
    *,
    field: str,
    maximum: int,
    required: bool,
) -> str:
    if not isinstance(value, str):
        raise _field_error(
            field,
            "Enter text.",
            "registration_setup_text_invalid",
        )
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if required and not normalized:
        raise _field_error(
            field,
            "This value is required.",
            "registration_setup_text_required",
        )
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise _field_error(
            field,
            "Control characters are not allowed.",
            "registration_setup_text_invalid",
        )
    if len(normalized) > maximum:
        raise _field_error(
            field,
            f"Use at most {maximum} characters.",
            "registration_setup_text_too_long",
        )
    return normalized


def _source_channel(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_SOURCE_CHANNEL_LENGTH
        or _SOURCE_CHANNEL_PATTERN.fullmatch(value) is None
    ):
        raise _field_error(
            "source_channel",
            "Use a registered source channel.",
            "registration_setup_source_channel_invalid",
        )
    return value


def _content_digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise _field_error(
            "content_digest",
            "Use the current lowercase SHA-256 content digest.",
            "registration_setup_content_digest_invalid",
        )
    return value


def _confirmation(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_EDITION_NAME_LENGTH
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise _field_error(
            "edition_name_confirmation",
            "Enter the exact current edition name.",
            "registration_setup_edition_confirmation_invalid",
        )
    return value


def _bounded[ItemT: Model](
    queryset: QuerySet[ItemT],
    *,
    limit: int,
) -> tuple[ItemT, ...]:
    rows = tuple(queryset[: limit + 1])
    if len(rows) > limit:
        raise RegistrationSetupLimitExceededError
    return rows


def _lock_scope(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
) -> _LockedConfigurationScope:
    organization = (
        Organization.objects.select_for_update().filter(pk=organization_id).first()
    )
    if organization is None:
        raise RegistrationSetupAuthorizationDeniedError
    series = (
        ConventionSeries.objects.select_for_update()
        .filter(pk=series_id, organization_id=organization.id)
        .first()
    )
    if series is None:
        raise RegistrationSetupAuthorizationDeniedError
    edition = (
        EventEdition.objects.select_for_update()
        .filter(
            pk=edition_id,
            organization_id=organization.id,
            series_id=series.id,
        )
        .first()
    )
    if edition is None:
        raise RegistrationSetupAuthorizationDeniedError
    control = (
        RegistrationSetupControl.objects.select_for_update()
        .filter(organization=organization, edition=edition)
        .first()
    )
    if control is None:
        raise RegistrationSetupStateConflictError
    persisted_actor = Account.objects.select_for_update().filter(pk=actor.pk).first()
    if persisted_actor is None:
        raise RegistrationSetupAuthorizationDeniedError
    evaluated_at = timezone.now()
    decision = _authorize_scope(
        actor=persisted_actor,
        organization_id=organization.id,
        series_id=series.id,
        edition_id=edition.id,
        at=evaluated_at,
    )
    configuration = (
        RegistrationConfiguration.objects.select_for_update()
        .filter(
            pk=configuration_id,
            organization=organization,
            edition=edition,
        )
        .first()
    )
    if configuration is None:
        raise RegistrationSetupStateConflictError
    sections = _bounded(
        RegistrationSection.objects.select_for_update()
        .filter(configuration=configuration)
        .order_by("position", "key", "id"),
        limit=MAX_SETUP_SECTIONS,
    )
    questions = _bounded(
        RegistrationQuestion.objects.select_for_update()
        .filter(configuration=configuration)
        .order_by("position", "key", "id"),
        limit=MAX_SETUP_QUESTIONS,
    )
    sections_by_id = {section.id: section for section in sections}
    for question in questions:
        if question.section_id is not None:
            section = sections_by_id.get(question.section_id)
            if section is None:
                raise RegistrationSetupDependencyError
            question.section = section
    products = _bounded(
        AdmissionProduct.objects.select_for_update()
        .filter(configuration=configuration)
        .order_by("position", "code", "id"),
        limit=MAX_SETUP_PRODUCTS,
    )
    minor_policy = (
        MinorRegistrationPolicy.objects.select_for_update()
        .select_related("reviewed_by")
        .filter(configuration=configuration)
        .first()
    )
    capacity_codes = tuple(
        ParticipationCapacity.objects.filter(
            participation__organization=organization,
            participation__edition=edition,
            status=ParticipationCapacity.Status.ACTIVE,
        )
        .order_by("code")
        .values_list("code", flat=True)
        .distinct()[: MAX_CAPACITY_CODES + 1]
    )
    if len(capacity_codes) > MAX_CAPACITY_CODES:
        raise RegistrationSetupLimitExceededError
    return _LockedConfigurationScope(
        organization=organization,
        series=series,
        edition=edition,
        actor=persisted_actor,
        control=control,
        configuration=configuration,
        sections=sections,
        questions=questions,
        products=products,
        minor_policy=minor_policy,
        active_capacity_codes=frozenset(capacity_codes),
        decision=decision,
        evaluated_at=evaluated_at,
    )


def _fresh_configuration_digest(scope: _LockedConfigurationScope) -> str:
    configuration = scope.configuration
    return configuration_content_digest(
        name=configuration.name,
        schema_version=int(configuration.version),
        opens_at=configuration.opens_at,
        closes_at=configuration.closes_at,
        capacity=int(configuration.capacity),
        capacity_ceiling=configuration.capacity_ceiling,
        currency=configuration.currency,
        minimum_age=int(configuration.minimum_age),
        default_payment_window_minutes=int(
            configuration.default_payment_window_minutes
        ),
        waitlist_enabled=configuration.waitlist_enabled,
        automatic_waitlist_promotion=configuration.automatic_waitlist_promotion,
        sections=scope.sections,
        questions=scope.questions,
        products=scope.products,
        minor_policy=scope.minor_policy,
    )


def _require_exact_configuration_digest(
    scope: _LockedConfigurationScope,
    *,
    submitted_digest: str | None = None,
) -> str:
    fresh = _fresh_configuration_digest(scope)
    if (
        not scope.configuration.content_digest
        or scope.configuration.content_digest != fresh
    ):
        raise RegistrationSetupDependencyError
    if submitted_digest is not None and submitted_digest != fresh:
        raise RegistrationSetupVersionConflictError
    return fresh


def _template_source_digest(template: RegistrationTemplate) -> str:
    sections = _bounded(
        RegistrationTemplateSection.objects.filter(template=template).order_by(
            "position", "key", "id"
        ),
        limit=MAX_SETUP_SECTIONS,
    )
    questions = _bounded(
        RegistrationTemplateQuestion.objects.filter(template=template).order_by(
            "position", "key", "id"
        ),
        limit=MAX_SETUP_QUESTIONS,
    )
    products = _bounded(
        RegistrationTemplateProduct.objects.filter(template=template).order_by(
            "position", "code", "id"
        ),
        limit=MAX_SETUP_PRODUCTS,
    )
    return template_content_digest(
        template=template,
        sections=sections,
        questions=questions,
        products=products,
    )


def _configuration_source_digest(configuration: RegistrationConfiguration) -> str:
    sections = _bounded(
        RegistrationSection.objects.filter(configuration=configuration).order_by(
            "position", "key", "id"
        ),
        limit=MAX_SETUP_SECTIONS,
    )
    questions = _bounded(
        RegistrationQuestion.objects.filter(configuration=configuration).order_by(
            "position", "key", "id"
        ),
        limit=MAX_SETUP_QUESTIONS,
    )
    products = _bounded(
        AdmissionProduct.objects.filter(configuration=configuration).order_by(
            "position", "code", "id"
        ),
        limit=MAX_SETUP_PRODUCTS,
    )
    policy = MinorRegistrationPolicy.objects.filter(configuration=configuration).first()
    return configuration_content_digest(
        name=configuration.name,
        schema_version=int(configuration.version),
        opens_at=configuration.opens_at,
        closes_at=configuration.closes_at,
        capacity=int(configuration.capacity),
        capacity_ceiling=configuration.capacity_ceiling,
        currency=configuration.currency,
        minimum_age=int(configuration.minimum_age),
        default_payment_window_minutes=int(
            configuration.default_payment_window_minutes
        ),
        waitlist_enabled=configuration.waitlist_enabled,
        automatic_waitlist_promotion=configuration.automatic_waitlist_promotion,
        sections=sections,
        questions=questions,
        products=products,
        minor_policy=policy,
    )


def _require_original_source_binding(
    *,
    configuration: RegistrationConfiguration,
    control: RegistrationSetupControl,
    organization: Organization,
    edition: EventEdition,
) -> RegistrationSetupCommandReceipt:
    expected_action = (
        RegistrationSetupCommandReceipt.Action.SUCCESSOR_STARTED
        if configuration.origin == RegistrationSetupOrigin.SUCCESSOR
        else RegistrationSetupCommandReceipt.Action.SETUP_STARTED
    )
    created_in_setup_version = configuration.created_in_setup_version
    if created_in_setup_version is None:
        raise RegistrationSetupDependencyError
    receipt = RegistrationSetupCommandReceipt.objects.filter(
        setup=control,
        resulting_version=created_in_setup_version,
        action=expected_action,
    ).first()
    if receipt is None:
        raise RegistrationSetupDependencyError
    targets = tuple(
        receipt.targets.filter(
            target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
            target_id=configuration.id,
            change_kind=RegistrationCommandChangeKind.CREATED,
        )[:2]
    )
    if (
        len(targets) != 1
        or targets[0].target_schema_version != configuration.version
        or targets[0].content_digest
        != configuration_source_binding_digest(configuration)
    ):
        raise RegistrationSetupDependencyError
    if (
        configuration.origin != RegistrationSetupOrigin.BLANK
        and receipt.actor_id != configuration.source_imported_by_id
    ):
        raise RegistrationSetupDependencyError
    try:
        _require_setup_start_evidence(
            scope=_SetupEvidenceScope(
                organization=organization,
                edition=edition,
                control=control,
            ),  # type: ignore[arg-type]
            receipt=receipt,
            configuration=configuration,
        )
    except RegistrationSetupStateConflictError as error:
        raise RegistrationSetupDependencyError from error
    return receipt


def _require_exact_source_digest(  # noqa: PLR0912
    scope: _LockedConfigurationScope,
) -> None:
    configuration = scope.configuration
    if (
        scope.control.origin != configuration.origin
        or scope.control.provenance_status != RegistrationProvenanceStatus.COMPLETE
        or configuration.provenance_status != RegistrationProvenanceStatus.COMPLETE
    ):
        raise RegistrationSetupDependencyError
    _require_original_source_binding(
        configuration=configuration,
        control=scope.control,
        organization=scope.organization,
        edition=scope.edition,
    )
    if configuration.origin == RegistrationSetupOrigin.BLANK:
        if any(
            (
                configuration.source_template_id,
                configuration.source_edition_id,
                configuration.source_configuration_id,
                configuration.source_version,
                configuration.source_content_digest,
                configuration.source_imported_at,
                configuration.source_imported_by_id,
            )
        ):
            raise RegistrationSetupDependencyError
        return
    if (
        configuration.source_version is None
        or not configuration.source_content_digest
        or configuration.source_imported_at is None
        or configuration.source_imported_by_id is None
    ):
        raise RegistrationSetupDependencyError
    if configuration.origin == RegistrationSetupOrigin.PUBLISHED_TEMPLATE:
        source_template_id = configuration.source_template_id
        if (
            source_template_id is None
            or configuration.source_edition_id is not None
            or configuration.source_configuration_id is not None
        ):
            raise RegistrationSetupDependencyError
        template = (
            RegistrationTemplate.objects.filter(
                pk=source_template_id,
                organization=scope.organization,
                status__in=(TemplateStatus.PUBLISHED, TemplateStatus.RETIRED),
            )
            .filter(series_id__isnull=True)
            .first()
        )
        if template is None:
            template = RegistrationTemplate.objects.filter(
                pk=source_template_id,
                organization=scope.organization,
                series=scope.series,
                status__in=(TemplateStatus.PUBLISHED, TemplateStatus.RETIRED),
            ).first()
        if template is None:
            raise RegistrationSetupDependencyError
        fresh = _template_source_digest(template)
        if (
            template.provenance_status != RegistrationProvenanceStatus.COMPLETE
            or template.created_in_catalog_version is None
            or template.last_changed_in_catalog_version is None
            or int(template.version) != int(configuration.source_version)
            or template.content_digest != fresh
            or configuration.source_content_digest != fresh
        ):
            raise RegistrationSetupDependencyError
        try:
            require_published_template_evidence(template)
        except RegistrationTemplateStateConflictError as error:
            raise RegistrationSetupDependencyError from error
        return
    if configuration.origin not in {
        RegistrationSetupOrigin.PRIOR_EDITION,
        RegistrationSetupOrigin.SUCCESSOR,
    }:
        raise RegistrationSetupDependencyError
    source_configuration_id = configuration.source_configuration_id
    source_edition_id = configuration.source_edition_id
    if (
        configuration.source_template_id is not None
        or source_configuration_id is None
        or source_edition_id is None
    ):
        raise RegistrationSetupDependencyError
    source = (
        RegistrationConfiguration.objects.select_related("edition")
        .filter(
            pk=source_configuration_id,
            organization=scope.organization,
            edition_id=source_edition_id,
            status__in=(ConfigurationStatus.ACTIVE, ConfigurationStatus.RETIRED),
        )
        .first()
    )
    if source is None:
        raise RegistrationSetupDependencyError
    if configuration.origin == RegistrationSetupOrigin.PRIOR_EDITION:
        # Eligibility was checked by the immutable setup-start command graph.
        # Edition dates remain legitimately editable later and must not strand
        # an already imported copy-on-write configuration.
        if source.edition_id == scope.edition.id:
            raise RegistrationSetupDependencyError
    elif source.edition_id != scope.edition.id:
        raise RegistrationSetupDependencyError
    source_control = RegistrationSetupControl.objects.filter(
        organization=scope.organization,
        edition=source.edition,
        origin=source.origin,
        provenance_status=RegistrationProvenanceStatus.COMPLETE,
    ).first()
    if (
        source.provenance_status != RegistrationProvenanceStatus.COMPLETE
        or source.created_in_setup_version is None
        or source.last_changed_in_setup_version is None
        or source_control is None
    ):
        raise RegistrationSetupDependencyError
    _require_original_source_binding(
        configuration=source,
        control=source_control,
        organization=scope.organization,
        edition=source.edition,
    )
    fresh = _configuration_source_digest(source)
    if (
        int(source.version) != int(configuration.source_version)
        or source.content_digest != fresh
        or configuration.source_content_digest != fresh
    ):
        raise RegistrationSetupDependencyError
    try:
        _require_active_configuration_lifecycle_evidence(
            scope=replace(
                scope,
                series=source.edition.series,
                edition=source.edition,
                control=source_control,
            ),  # type: ignore[arg-type]
            configuration=source,
            content_digest=fresh,
        )
    except RegistrationSetupStateConflictError as error:
        raise RegistrationSetupDependencyError from error


def _validation_codes(error: ValidationError) -> tuple[str, ...]:
    if hasattr(error, "error_dict"):
        errors = [item for values in error.error_dict.values() for item in values]
    else:
        errors = list(error.error_list)
    return tuple(sorted({item.code or "invalid" for item in errors}))


def _model_issues(
    instance: Model,
    *,
    target_kind: str,
    target_key: str,
) -> list[RegistrationConfigurationIssue]:
    try:
        instance.full_clean()
    except ValidationError as error:
        return [
            RegistrationConfigurationIssue(code, target_kind, target_key)
            for code in _validation_codes(error)
        ]
    return []


def _minor_policy_target_digest(policy: MinorRegistrationPolicy) -> str:
    payload = minor_policy_payload(policy)
    if payload is None:
        raise RegistrationSetupStateConflictError
    return target_content_digest(kind="minor_policy", payload=payload)


def _minor_policy_request_digest(
    *,
    scope: _LockedConfigurationScope | _MinorPolicyEvidenceScope,
    receipt: RegistrationSetupCommandReceipt,
    policy: MinorRegistrationPolicy,
) -> str:
    action = receipt.action
    if action not in {
        RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED,
        RegistrationSetupCommandReceipt.Action.MINOR_POLICY_UPDATED,
    }:
        raise RegistrationSetupStateConflictError
    return canonical_digest(
        {
            "action": action,
            "actor_id": str(receipt.actor_id),
            "organization_id": str(scope.organization.id),
            "series_id": str(scope.series.id),
            "edition_id": str(scope.edition.id),
            "configuration_id": str(scope.configuration.id),
            "policy_id": (
                None
                if action == RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED
                else str(policy.id)
            ),
            "enabled": policy.enabled,
            "minor_age_threshold": policy.minor_age_threshold,
            "guardian_notice_version": policy.guardian_notice_version,
            "jurisdiction_code": policy.jurisdiction_code,
            "review_reference": policy.review_reference,
            "expected_version": int(receipt.resulting_version) - 1,
            "reason": receipt.reason,
        }
    )


def _require_minor_policy_review_evidence(
    *,
    scope: _LockedConfigurationScope | _MinorPolicyEvidenceScope,
    policy: MinorRegistrationPolicy,
    visited_configuration_ids: frozenset[UUID] = frozenset(),
) -> AuditEvent:
    """Prove reviewer identity/time from an immutable command graph.

    Parameters
    ----------
    scope : _LockedConfigurationScope | _MinorPolicyEvidenceScope
        The exact tenant and resource scope of the operation.
    policy : MinorRegistrationPolicy
        The closed policy definition governing the requested decision.
    visited_configuration_ids : frozenset[UUID], default=frozenset()
        The selected visited configuration identifiers.

    Returns
    -------
    AuditEvent
        The resolved AuditEvent for require minor policy review evidence.

    Raises
    ------
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    configuration = scope.configuration
    if (
        configuration.id in visited_configuration_ids
        or policy.configuration_id != configuration.id
        or policy.reviewed_by_id is None
        or policy.reviewed_at is None
        or policy.reviewed_at > scope.evaluated_at
        or policy.last_changed_in_setup_version is None
        or policy.last_changed_in_setup_version <= 0
        or policy.last_changed_in_setup_version > scope.control.aggregate_version
    ):
        raise RegistrationSetupStateConflictError
    receipt = (
        RegistrationSetupCommandReceipt.objects.select_for_update()
        .filter(
            setup=scope.control,
            resulting_version=policy.last_changed_in_setup_version,
        )
        .first()
    )
    if receipt is None:
        raise RegistrationSetupStateConflictError
    if receipt.action == RegistrationSetupCommandReceipt.Action.SETUP_STARTED:
        if (
            configuration.origin != RegistrationSetupOrigin.PRIOR_EDITION
            or policy.created_in_setup_version != receipt.resulting_version
            or receipt.resulting_version != configuration.created_in_setup_version
        ):
            raise RegistrationSetupStateConflictError
        setup_audit = _require_setup_start_evidence(
            scope=_SetupEvidenceScope(
                organization=scope.organization,
                edition=scope.edition,
                control=scope.control,
            ),  # type: ignore[arg-type]
            receipt=receipt,
            configuration=configuration,
        )
        policy_targets = tuple(
            receipt.targets.select_for_update().filter(
                target_kind=RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
                target_id=policy.id,
                change_kind=RegistrationCommandChangeKind.CREATED,
            )[:2]
        )
        if (
            len(policy_targets) != 1
            or policy_targets[0].target_schema_version is not None
            or policy_targets[0].content_digest != _minor_policy_target_digest(policy)
            or configuration.source_configuration_id is None
            or configuration.source_edition_id is None
        ):
            raise RegistrationSetupStateConflictError
        source = (
            RegistrationConfiguration.objects.select_for_update()
            .select_related("edition", "edition__series")
            .filter(
                pk=configuration.source_configuration_id,
                organization=scope.organization,
                edition_id=configuration.source_edition_id,
                status__in=(ConfigurationStatus.ACTIVE, ConfigurationStatus.RETIRED),
            )
            .first()
        )
        if source is None:
            raise RegistrationSetupStateConflictError
        source_control = (
            RegistrationSetupControl.objects.select_for_update()
            .filter(
                organization=scope.organization,
                edition=source.edition,
                origin=source.origin,
                provenance_status=RegistrationProvenanceStatus.COMPLETE,
            )
            .first()
        )
        source_policy = (
            MinorRegistrationPolicy.objects.select_for_update()
            .filter(configuration=source)
            .first()
        )
        if (
            source_control is None
            or source_policy is None
            or minor_policy_payload(source_policy) != minor_policy_payload(policy)
        ):
            raise RegistrationSetupStateConflictError
        _require_original_source_binding(
            configuration=source,
            control=source_control,
            organization=scope.organization,
            edition=source.edition,
        )
        _require_minor_policy_review_evidence(
            scope=_MinorPolicyEvidenceScope(
                organization=scope.organization,
                series=source.edition.series,
                edition=source.edition,
                control=source_control,
                configuration=source,
                evaluated_at=scope.evaluated_at,
            ),
            policy=source_policy,
            visited_configuration_ids=(
                visited_configuration_ids | frozenset({configuration.id})
            ),
        )
        return setup_audit

    if (
        receipt.action
        not in {
            RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED,
            RegistrationSetupCommandReceipt.Action.MINOR_POLICY_UPDATED,
        }
        or receipt.actor_id != policy.reviewed_by_id
        or receipt.request_digest
        != _minor_policy_request_digest(scope=scope, receipt=receipt, policy=policy)
    ):
        raise RegistrationSetupStateConflictError
    targets = tuple(
        receipt.targets.select_for_update().order_by("target_kind", "target_id", "id")
    )
    configuration_targets = tuple(
        target
        for target in targets
        if target.target_kind == RegistrationSetupCommandTarget.TargetKind.CONFIGURATION
        and target.target_id == configuration.id
        and target.change_kind == RegistrationCommandChangeKind.UPDATED
        and target.target_schema_version == configuration.version
    )
    expected_change_kind = (
        RegistrationCommandChangeKind.CREATED
        if receipt.action == RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED
        else RegistrationCommandChangeKind.UPDATED
    )
    policy_targets = tuple(
        target
        for target in targets
        if target.target_kind == RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY
        and target.target_id == policy.id
        and target.change_kind == expected_change_kind
        and target.target_schema_version is None
        and target.content_digest == _minor_policy_target_digest(policy)
    )
    if (
        len(targets) != MINOR_POLICY_COMMAND_TARGET_COUNT
        or len(configuration_targets) != 1
        or len(policy_targets) != 1
    ):
        raise RegistrationSetupStateConflictError
    allowed_changed_fields = {
        "enabled",
        "minor_age_threshold",
        "guardian_notice_version",
        "jurisdiction_code",
        "review_reference",
    }
    changed_fields: tuple[str, ...]
    if receipt.action == RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED:
        changed_fields = (
            "enabled",
            "minor_age_threshold",
            "guardian_notice_version",
            "jurisdiction_code",
            "review_reference",
        )
    else:
        audits = tuple(
            AuditEvent.objects.select_for_update().filter(
                organization_id=scope.organization.id,
                event_edition_id=scope.edition.id,
                correlation_id=receipt.correlation_id,
                operation="registration.setup.minor_policy.changed",
                target_type="registration.minor_policy",
                target_id=policy.id,
            )[:2]
        )
        if (
            len(audits) != 1
            or not audits[0].changed_fields
            or any(
                field not in allowed_changed_fields
                for field in audits[0].changed_fields
            )
        ):
            raise RegistrationSetupStateConflictError
        changed_fields = tuple(audits[0].changed_fields)
    return require_setup_command_evidence_graph(
        scope=scope,
        receipt=receipt,
        primary_target_id=policy.id,
        operation_segment="minor_policy",
        expected_targets=(
            SetupCommandTargetExpectation(
                target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
                target_id=configuration.id,
                change_kind=RegistrationCommandChangeKind.UPDATED,
                target_schema_version=configuration.version,
                content_digest=configuration_targets[0].content_digest,
            ),
            SetupCommandTargetExpectation(
                target_kind=RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
                target_id=policy.id,
                change_kind=expected_change_kind,
                target_schema_version=None,
                content_digest=_minor_policy_target_digest(policy),
            ),
        ),
        expected_changed_fields=changed_fields,
        expected_event_payload={
            "action": receipt.action,
            "configuration_version": str(configuration.version),
        },
        expected_occurred_at=policy.reviewed_at,
    )


def _configuration_issues(  # noqa: PLR0912, PLR0915
    scope: _LockedConfigurationScope,
) -> tuple[RegistrationConfigurationIssue, ...]:
    configuration = scope.configuration
    issues: list[RegistrationConfigurationIssue] = []
    issues.extend(
        _model_issues(
            configuration,
            target_kind="configuration",
            target_key="configuration",
        )
    )
    if timezone.is_naive(configuration.opens_at) or timezone.is_naive(
        configuration.closes_at
    ):
        issues.append(
            RegistrationConfigurationIssue(
                "registration_setup_period_timezone_invalid",
                "configuration",
                "configuration",
            )
        )
    if configuration.currency not in scope.edition.currency_codes:
        issues.append(
            RegistrationConfigurationIssue(
                "registration_setup_currency_invalid",
                "configuration",
                "configuration",
            )
        )
    if (
        not configuration.waitlist_enabled
        and configuration.automatic_waitlist_promotion
    ):
        issues.append(
            RegistrationConfigurationIssue(
                "registration_setup_waitlist_invalid",
                "configuration",
                "configuration",
            )
        )
    if not (
        MINIMUM_PAYMENT_WINDOW_MINUTES
        <= configuration.default_payment_window_minutes
        <= MAXIMUM_PAYMENT_WINDOW_MINUTES
    ):
        issues.append(
            RegistrationConfigurationIssue(
                "registration_setup_payment_window_invalid",
                "configuration",
                "configuration",
            )
        )

    for section in scope.sections:
        issues.extend(
            _model_issues(
                section,
                target_kind="section",
                target_key=section.key,
            )
        )

    question_by_key: dict[str, RegistrationQuestion] = {}
    for question in scope.questions:
        issues.extend(
            _model_issues(
                question,
                target_kind="question",
                target_key=question.key,
            )
        )
        if len(question.help_text) > MAX_QUESTION_HELP_LENGTH:
            issues.append(
                RegistrationConfigurationIssue(
                    "registration_question_help_too_long",
                    "question",
                    question.key,
                )
            )
        source_key = question.condition_question_key
        if source_key:
            source = question_by_key.get(source_key)
            if source is None or source.position >= question.position:
                issues.append(
                    RegistrationConfigurationIssue(
                        "registration_condition_source_not_prior",
                        "question",
                        question.key,
                    )
                )
            else:
                if (
                    question.visibility == QuestionVisibility.ATTENDEE_AND_STAFF
                    and source.visibility == QuestionVisibility.REGISTRATION_STAFF
                ):
                    issues.append(
                        RegistrationConfigurationIssue(
                            "registration_condition_visibility_incompatible",
                            "question",
                            question.key,
                        )
                    )
                if not condition_value_is_compatible(
                    field_type=source.field_type,
                    options=source.options,
                    value=question.condition_value,
                ):
                    issues.append(
                        RegistrationConfigurationIssue(
                            "registration_condition_value_incompatible",
                            "question",
                            question.key,
                        )
                    )
        question_by_key[question.key] = question

    if not scope.products:
        issues.append(
            RegistrationConfigurationIssue(
                "registration_products_required",
                "configuration",
                "configuration",
            )
        )
    for product in scope.products:
        issues.extend(
            _model_issues(
                product,
                target_kind="product",
                target_key=product.code,
            )
        )
        if len(product.description) > MAX_PRODUCT_DESCRIPTION_LENGTH:
            issues.append(
                RegistrationConfigurationIssue(
                    "registration_product_description_too_long",
                    "product",
                    product.code,
                )
            )
        if (product.sales_open_at is None) != (product.sales_close_at is None):
            issues.append(
                RegistrationConfigurationIssue(
                    "product_sales_period_incomplete",
                    "product",
                    product.code,
                )
            )
        if product.capacity > configuration.capacity:
            issues.append(
                RegistrationConfigurationIssue(
                    "product_capacity_exceeds_configuration",
                    "product",
                    product.code,
                )
            )
        if not configuration.waitlist_enabled and product.waitlist_enabled:
            issues.append(
                RegistrationConfigurationIssue(
                    "product_waitlist_exceeds_configuration",
                    "product",
                    product.code,
                )
            )
        if product.sales_open_at is not None and (
            timezone.is_naive(product.sales_open_at)
            or product.sales_open_at < configuration.opens_at
        ):
            issues.append(
                RegistrationConfigurationIssue(
                    "product_sales_before_registration",
                    "product",
                    product.code,
                )
            )
        if product.sales_close_at is not None and (
            timezone.is_naive(product.sales_close_at)
            or product.sales_close_at > configuration.closes_at
        ):
            issues.append(
                RegistrationConfigurationIssue(
                    "product_sales_after_registration",
                    "product",
                    product.code,
                )
            )
        if product.payment_window_minutes is not None and not (
            MINIMUM_PAYMENT_WINDOW_MINUTES
            <= product.payment_window_minutes
            <= MAXIMUM_PAYMENT_WINDOW_MINUTES
        ):
            issues.append(
                RegistrationConfigurationIssue(
                    "product_payment_window_invalid",
                    "product",
                    product.code,
                )
            )
        if not set(product.required_capacity_codes).issubset(
            scope.active_capacity_codes
        ):
            issues.append(
                RegistrationConfigurationIssue(
                    "product_capacity_code_unavailable",
                    "product",
                    product.code,
                )
            )

    if configuration.minimum_age < DEFAULT_ADULT_AGE:
        policy = scope.minor_policy
        if policy is None or not policy.enabled:
            issues.append(
                RegistrationConfigurationIssue(
                    "minor_policy_required",
                    "configuration",
                    "configuration",
                )
            )
        else:
            issues.extend(
                _model_issues(
                    policy,
                    target_kind="minor_policy",
                    target_key="minor_policy",
                )
            )
            try:
                _require_minor_policy_review_evidence(scope=scope, policy=policy)
            except (
                RegistrationSetupStateConflictError,
                RegistrationSetupDependencyError,
            ):
                issues.append(
                    RegistrationConfigurationIssue(
                        "minor_policy_review_invalid",
                        "minor_policy",
                        "minor_policy",
                    )
                )

    return tuple(sorted(set(issues)))


def _configuration_command_request_digest(
    *,
    scope: _LockedConfigurationScope,
    receipt: RegistrationSetupCommandReceipt,
    content_digest: str,
) -> str:
    payload: dict[str, object] = {
        "action": receipt.action,
        "actor_id": str(receipt.actor_id),
        "organization_id": str(scope.organization.id),
        "series_id": str(scope.series.id),
        "edition_id": str(scope.edition.id),
        "configuration_id": str(scope.configuration.id),
        "content_digest": content_digest,
    }
    if receipt.action == RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED:
        payload["review_note"] = scope.configuration.review_note
    elif (
        receipt.action == RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED
    ):
        payload["edition_name_confirmation"] = scope.edition.name
    else:
        raise RegistrationSetupStateConflictError
    payload["expected_version"] = int(receipt.resulting_version) - 1
    payload["reason"] = receipt.reason
    return canonical_digest(payload)


def _require_configuration_command_evidence(
    *,
    scope: _LockedConfigurationScope,
    receipt: RegistrationSetupCommandReceipt,
    content_digest: str,
) -> AuditEvent:
    action = receipt.action
    changed_fields: tuple[str, ...]
    if (
        receipt.action == RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED
        and receipt.request_digest
        != _configuration_command_request_digest(
            scope=scope,
            receipt=receipt,
            content_digest=content_digest,
        )
    ) or _SHA256_PATTERN.fullmatch(receipt.request_digest) is None:
        raise RegistrationSetupStateConflictError
    if action == RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED:
        change_kind = RegistrationCommandChangeKind.REVIEWED
        changed_fields = ("review_state",)
        event_name = "registration.configuration.draft_changed.v1"
        event_payload: dict[str, object] = {
            "action": action,
            "configuration_version": str(scope.configuration.version),
        }
        expected_occurred_at = None
    elif action == RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED:
        change_kind = RegistrationCommandChangeKind.ACTIVATED
        changed_fields = ("status", "activated_at")
        event_name = "registration.configuration.activated.v1"
        event_payload = {
            "configuration_version": str(scope.configuration.version),
            "source_kind": scope.configuration.origin,
        }
        expected_occurred_at = scope.configuration.activated_at
    else:
        raise RegistrationSetupStateConflictError
    audit = require_setup_command_evidence_graph(
        scope=scope,
        receipt=receipt,
        primary_target_id=scope.configuration.id,
        operation_segment="configuration",
        expected_targets=(
            SetupCommandTargetExpectation(
                target_kind=(RegistrationSetupCommandTarget.TargetKind.CONFIGURATION),
                target_id=scope.configuration.id,
                change_kind=change_kind,
                target_schema_version=scope.configuration.version,
                content_digest=content_digest,
            ),
        ),
        expected_changed_fields=changed_fields,
        expected_event_payload=event_payload,
        expected_occurred_at=expected_occurred_at,
        expected_audit_operation=f"registration.setup.{action}",
        expected_audit_target_type="registration.configuration",
        expected_contract_version="registration-configuration-lifecycle-v1",
        expected_event_name=event_name,
    )
    if (
        action == RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED
        and scope.configuration.activated_at != audit.occurred_at
    ):
        raise RegistrationSetupStateConflictError
    return audit


def _review_resolved(  # noqa: PLR0911
    scope: _LockedConfigurationScope,
    digest: str,
) -> bool:
    configuration_version = int(scope.configuration.last_changed_in_setup_version or 0)
    if not 0 < configuration_version <= int(scope.control.aggregate_version):
        return False
    if scope.configuration.status == ConfigurationStatus.DRAFT:
        receipt = RegistrationSetupCommandReceipt.objects.filter(
            setup=scope.control,
            resulting_version=configuration_version,
            action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED,
        ).first()
        if receipt is None or scope.configuration.review_required:
            return False
        try:
            _require_configuration_command_evidence(
                scope=scope,
                receipt=receipt,
                content_digest=digest,
            )
        except RegistrationSetupStateConflictError:
            return False
        return True
    if (
        scope.configuration.status != ConfigurationStatus.ACTIVE
        or configuration_version <= 1
    ):
        return False
    activation = RegistrationSetupCommandReceipt.objects.filter(
        setup=scope.control,
        resulting_version=configuration_version,
        action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED,
    ).first()
    review = RegistrationSetupCommandReceipt.objects.filter(
        setup=scope.control,
        resulting_version=configuration_version - 1,
        action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED,
    ).first()
    if activation is None or review is None or scope.configuration.review_required:
        return False
    try:
        activation_audit = _require_configuration_command_evidence(
            scope=scope,
            receipt=activation,
            content_digest=digest,
        )
        review_audit = _require_configuration_command_evidence(
            scope=scope,
            receipt=review,
            content_digest=digest,
        )
    except RegistrationSetupStateConflictError:
        return False
    return review_audit.occurred_at <= activation_audit.occurred_at


def _answer_validation(
    *,
    questions: tuple[RegistrationQuestion, ...],
    answers: object | None,
    include_staff_questions: bool,
) -> RegistrationPreviewAnswerValidation:
    schema_questions = tuple(
        question
        for question in questions
        if include_staff_questions
        or question.visibility == QuestionVisibility.ATTENDEE_AND_STAFF
    )
    schema_keys = tuple(question.key for question in schema_questions)
    if answers is None:
        return RegistrationPreviewAnswerValidation(
            requested=False,
            valid=None,
            schema_keys=schema_keys,
            normalized_answer_keys=(),
            error_fields=(),
            error_codes=(),
        )
    try:
        normalized, schema = validate_registration_answers(
            questions=questions,
            answers=answers,
            include_staff_questions=include_staff_questions,
        )
    except ValidationError as error:
        fields = (
            tuple(sorted(error.error_dict))
            if hasattr(error, "error_dict")
            else ("answers",)
        )
        return RegistrationPreviewAnswerValidation(
            requested=True,
            valid=False,
            schema_keys=schema_keys,
            normalized_answer_keys=(),
            error_fields=fields,
            error_codes=_validation_codes(error),
        )
    projected_keys = tuple(str(item["key"]) for item in schema)
    return RegistrationPreviewAnswerValidation(
        requested=True,
        valid=True,
        schema_keys=projected_keys,
        normalized_answer_keys=tuple(normalized),
        error_fields=(),
        error_codes=(),
    )


def _receipt_for_retry(
    scope: _LockedConfigurationScope,
    retry_key: UUID,
) -> RegistrationSetupCommandReceipt | None:
    return (
        RegistrationSetupCommandReceipt.objects.select_for_update()
        .filter(
            organization=scope.organization,
            edition=scope.edition,
            actor=scope.actor,
            retry_key=retry_key,
        )
        .first()
    )


def _result_from_receipt(
    *,
    scope: _LockedConfigurationScope,
    receipt: RegistrationSetupCommandReceipt,
    action: str,
    request_digest: str,
    content_digest: str,
) -> RegistrationConfigurationLifecycleResult:
    if receipt.action != action or receipt.request_digest != request_digest:
        raise RegistrationSetupRetryConflictError
    try:
        digest = _require_exact_configuration_digest(
            scope,
            submitted_digest=content_digest,
        )
        _require_exact_source_digest(scope)
        _require_configuration_command_evidence(
            scope=scope,
            receipt=receipt,
            content_digest=digest,
        )
    except RegistrationSetupVersionConflictError as error:
        raise RegistrationSetupStateConflictError from error
    if not _review_resolved(scope, digest):
        raise RegistrationSetupStateConflictError
    configuration_version = int(scope.configuration.last_changed_in_setup_version or 0)
    if action == RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED:
        persisted = (
            scope.configuration.status == ConfigurationStatus.DRAFT
            and configuration_version == receipt.resulting_version
        ) or (
            scope.configuration.status == ConfigurationStatus.ACTIVE
            and configuration_version == receipt.resulting_version + 1
        )
    else:
        persisted = (
            scope.configuration.status == ConfigurationStatus.ACTIVE
            and configuration_version == receipt.resulting_version
            and scope.configuration.activated_at is not None
        )
    if not persisted:
        raise RegistrationSetupStateConflictError
    return RegistrationConfigurationLifecycleResult(
        setup_id=scope.control.id,
        configuration_id=scope.configuration.id,
        receipt_id=receipt.id,
        resulting_version=int(receipt.resulting_version),
        configuration_version=int(scope.configuration.version),
        status=(
            ConfigurationStatus.DRAFT
            if action == RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED
            else ConfigurationStatus.ACTIVE
        ),
        content_digest=digest,
        review_resolved=True,
        replayed=True,
    )


def _append_command_evidence(
    *,
    scope: _LockedConfigurationScope,
    action: str,
    change_kind: str,
    resulting_version: int,
    content_digest: str,
    reason: str,
    retry_key: UUID,
    request_digest: str,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
) -> RegistrationSetupCommandReceipt:
    receipt = RegistrationSetupCommandReceipt.objects.create(
        setup=scope.control,
        organization=scope.organization,
        edition=scope.edition,
        action=action,
        resulting_version=resulting_version,
        actor=scope.actor,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    RegistrationSetupCommandTarget.objects.create(
        receipt=receipt,
        target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
        target_id=scope.configuration.id,
        change_kind=change_kind,
        target_schema_version=scope.configuration.version,
        content_digest=content_digest,
    )
    audit_event = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor.id,
            principal_context_id=None,
            organization_id=scope.organization.id,
            event_edition_id=scope.edition.id,
            capability_code="registration.manage_configuration",
            operation=f"registration.setup.{action}",
            target_type="registration.configuration",
            target_id=scope.configuration.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            changed_fields=(
                ("review_state",)
                if action
                == RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED
                else ("status", "activated_at")
            ),
            idempotency_key_hash=canonical_digest({"retry_key": str(retry_key)}),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "contract_version": "registration-configuration-lifecycle-v1",
                "target_count": 1,
            },
            retention_class="registration-restricted",
        ),
        occurred_at=scope.evaluated_at,
    )
    if action == RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED:
        event_name = "registration.configuration.draft_changed.v1"
        payload: dict[str, object] = {
            "action": action,
            "configuration_version": str(scope.configuration.version),
        }
    else:
        event_name = "registration.configuration.activated.v1"
        payload = {
            "configuration_version": str(scope.configuration.version),
            "source_kind": scope.configuration.origin,
        }
    publish_domain_event(
        DomainEventRecord(
            event_name=event_name,
            schema_version=1,
            organization_id=scope.organization.id,
            event_edition_id=scope.edition.id,
            aggregate_type="registration.setup",
            aggregate_id=scope.control.id,
            aggregate_version=resulting_version,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=audit_event.id,
            actor_kind="account",
            actor_id=scope.actor.id,
            retention_class="registration-restricted",
        ),
        occurred_at=scope.evaluated_at,
    )
    return receipt


def _require_editable_draft(scope: _LockedConfigurationScope) -> None:
    if (
        scope.organization.lifecycle not in _EDITABLE_ORGANIZATION_LIFECYCLES
        or scope.edition.lifecycle not in _EDITABLE_EDITION_LIFECYCLES
        or scope.configuration.status != ConfigurationStatus.DRAFT
    ):
        raise RegistrationSetupLifecycleConflictError


def _require_current_version(
    scope: _LockedConfigurationScope,
    expected_version: int,
) -> int:
    current = int(scope.control.aggregate_version)
    if current != expected_version:
        raise RegistrationSetupVersionConflictError
    return current


def preview_registration_configuration(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    attendee_answers: object | None = None,
    staff_answers: object | None = None,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationConfigurationPreview:
    """Return a coherent, audited preview without creating domain records.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    series_id : UUID
        The convention-series identifier within the organization scope.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    configuration_id : UUID
        The configuration identifier within the requested scope.
    attendee_answers : object | None, default=None
        The attendee answers evaluated while preview registration configuration.
    staff_answers : object | None, default=None
        The staff answers evaluated while preview registration configuration.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RegistrationConfigurationPreview
        The RegistrationConfigurationPreview produced by preview registration
        configuration.
    """
    _authorize_scope(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            configuration_id=configuration_id,
        )
        digest = _require_exact_configuration_digest(scope)
        _require_exact_source_digest(scope)
        issues = _configuration_issues(scope)
        attendee_validation = _answer_validation(
            questions=scope.questions,
            answers=attendee_answers,
            include_staff_questions=False,
        )
        staff_validation = _answer_validation(
            questions=scope.questions,
            answers=staff_answers,
            include_staff_questions=True,
        )
        final_decision = _authorize_scope(
            actor=scope.actor,
            organization_id=scope.organization.id,
            series_id=scope.series.id,
            edition_id=scope.edition.id,
        )
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=scope.actor.id,
                principal_context_id=None,
                organization_id=scope.organization.id,
                event_edition_id=scope.edition.id,
                capability_code="registration.manage_configuration",
                operation="registration.setup.preview",
                target_type="registration.configuration",
                target_id=scope.configuration.id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=final_decision.reason_code,
                correlation_id=correlation_id,
                request_id=request_id or correlation_id,
                source_channel=source_channel,
                obligations=tuple(sorted(final_decision.obligations)),
                safe_metadata={
                    "policy_version": POLICY_VERSION,
                    "contract_version": "registration-configuration-preview-v1",
                    "target_count": (
                        1
                        + len(scope.sections)
                        + len(scope.questions)
                        + len(scope.products)
                        + int(scope.minor_policy is not None)
                    ),
                },
                retention_class="registration-restricted",
            ),
            occurred_at=timezone.now(),
        )
        section_keys = {section.id: section.key for section in scope.sections}
        return RegistrationConfigurationPreview(
            setup_id=scope.control.id,
            configuration_id=scope.configuration.id,
            aggregate_version=int(scope.control.aggregate_version),
            configuration_version=int(scope.configuration.version),
            status=scope.configuration.status,
            origin=scope.configuration.origin,
            content_digest=digest,
            source_content_digest=scope.configuration.source_content_digest,
            review_resolved=_review_resolved(scope, digest),
            name=scope.configuration.name,
            edition_name=scope.edition.name,
            opens_at=scope.configuration.opens_at,
            closes_at=scope.configuration.closes_at,
            capacity=int(scope.configuration.capacity),
            currency=scope.configuration.currency,
            minimum_age=int(scope.configuration.minimum_age),
            default_payment_window_minutes=int(
                scope.configuration.default_payment_window_minutes
            ),
            waitlist_enabled=scope.configuration.waitlist_enabled,
            automatic_waitlist_promotion=(
                scope.configuration.automatic_waitlist_promotion
            ),
            sections=tuple(
                RegistrationPreviewSection(
                    key=section.key,
                    title=section.title,
                    description=section.description,
                    position=int(section.position),
                )
                for section in scope.sections
            ),
            questions=tuple(
                RegistrationPreviewQuestion(
                    key=question.key,
                    label=question.label,
                    help_text=question.help_text,
                    field_type=question.field_type,
                    required=question.required,
                    options=tuple(question.options),
                    purpose=question.purpose,
                    visibility=question.visibility,
                    classification=question.classification,
                    condition_question_key=question.condition_question_key,
                    condition_value=question.condition_value,
                    section_key=(
                        section_keys.get(question.section_id, "")
                        if question.section_id is not None
                        else ""
                    ),
                    attendee_input=(
                        question.visibility == QuestionVisibility.ATTENDEE_AND_STAFF
                    ),
                    staff_input=True,
                )
                for question in scope.questions
            ),
            products=tuple(
                RegistrationPreviewProduct(
                    code=product.code,
                    name=product.name,
                    description=product.description,
                    price_minor=int(product.price_minor),
                    capacity=int(product.capacity),
                    entitlement_code=product.entitlement_code,
                    entitlement_name=product.entitlement_name,
                    sales_open_at=product.sales_open_at,
                    sales_close_at=product.sales_close_at,
                    required_capacity_codes=tuple(product.required_capacity_codes),
                    eligibility_explanation=product.eligibility_explanation,
                    waitlist_enabled=product.waitlist_enabled,
                    payment_window_minutes=product.payment_window_minutes,
                    status=product.status,
                )
                for product in scope.products
            ),
            validation_issues=issues,
            attendee_answers=attendee_validation,
            staff_answers=staff_validation,
            forbidden_effects=RegistrationPreviewForbiddenEffects(),
        )


def review_registration_configuration(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    content_digest: str,
    review_note: str,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationConfigurationLifecycleResult:
    """Resolve review for exactly one valid draft content generation.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    series_id : UUID
        The convention-series identifier within the organization scope.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    configuration_id : UUID
        The configuration identifier within the requested scope.
    content_digest : str
        The canonical digest used to verify content.
    review_note : str
        The review note evaluated while review registration configuration.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    reason : str
        The operator-supplied rationale recorded with the change.
    retry_key : UUID
        The stable key that makes an exact command retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RegistrationConfigurationLifecycleResult
        The RegistrationConfigurationLifecycleResult produced by review
        registration configuration.

    Raises
    ------
    RegistrationConfigurationValidationError
        If the operation encounters a registration configuration validation
        condition.
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    _field_error
        If the operation encounters a field error condition.
    """
    _authorize_scope(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    content_digest = _content_digest(content_digest)
    review_note = _normalized_text(
        review_note,
        field="review_note",
        maximum=MAX_REVIEW_NOTE_LENGTH,
        required=False,
    )
    expected_version = _expected_version(expected_version)
    reason = _normalized_text(
        reason,
        field="reason",
        maximum=MAX_REASON_LENGTH,
        required=True,
    )
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED
    request_digest = canonical_digest(
        {
            "action": action,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "content_digest": content_digest,
            "review_note": review_note,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            configuration_id=configuration_id,
        )
        replay = _receipt_for_retry(scope, retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=action,
                request_digest=request_digest,
                content_digest=content_digest,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        digest = _require_exact_configuration_digest(
            scope,
            submitted_digest=content_digest,
        )
        _require_exact_source_digest(scope)
        if (
            scope.configuration.origin != RegistrationSetupOrigin.BLANK
            and not review_note
        ):
            raise _field_error(
                "review_note",
                "Imported registration setup requires a review note.",
                "registration_setup_review_note_required",
            )
        if _review_resolved(scope, digest):
            raise RegistrationSetupStateConflictError
        issues = _configuration_issues(scope)
        if issues:
            raise RegistrationConfigurationValidationError(issues)
        resulting_version = current_version + 1
        scope.configuration.review_required = False
        scope.configuration.review_note = review_note
        scope.configuration.last_changed_in_setup_version = resulting_version
        scope.configuration.save(
            update_fields=(
                "review_required",
                "review_note",
                "last_changed_in_setup_version",
                "updated_at",
            )
        )
        scope.control.aggregate_version = resulting_version
        scope.control.save(update_fields=("aggregate_version", "updated_at"))
        receipt = _append_command_evidence(
            scope=scope,
            action=action,
            change_kind=RegistrationCommandChangeKind.REVIEWED,
            resulting_version=resulting_version,
            content_digest=digest,
            reason=reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        _require_configuration_command_evidence(
            scope=scope,
            receipt=receipt,
            content_digest=digest,
        )
        if not _review_resolved(scope, digest):
            raise RegistrationSetupStateConflictError
        return RegistrationConfigurationLifecycleResult(
            setup_id=scope.control.id,
            configuration_id=scope.configuration.id,
            receipt_id=receipt.id,
            resulting_version=resulting_version,
            configuration_version=int(scope.configuration.version),
            status=scope.configuration.status,
            content_digest=digest,
            review_resolved=True,
            replayed=False,
        )


def activate_registration_configuration(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    content_digest: str,
    edition_name_confirmation: str,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationConfigurationLifecycleResult:
    """Activate one reviewed draft without silently retiring another version.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    series_id : UUID
        The convention-series identifier within the organization scope.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    configuration_id : UUID
        The configuration identifier within the requested scope.
    content_digest : str
        The canonical digest used to verify content.
    edition_name_confirmation : str
        The exact edition name required to confirm activation intent.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    reason : str
        The operator-supplied rationale recorded with the change.
    retry_key : UUID
        The stable key that makes an exact command retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RegistrationConfigurationLifecycleResult
        The RegistrationConfigurationLifecycleResult produced by activate
        registration configuration.

    Raises
    ------
    RegistrationConfigurationActiveConflictError
        If the operation encounters a registration configuration active conflict
        condition.
    RegistrationConfigurationReviewRequiredError
        If the operation encounters a registration configuration review required
        condition.
    RegistrationConfigurationValidationError
        If the operation encounters a registration configuration validation
        condition.
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    _field_error
        If the operation encounters a field error condition.
    """
    _authorize_scope(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    content_digest = _content_digest(content_digest)
    edition_name_confirmation = _confirmation(edition_name_confirmation)
    expected_version = _expected_version(expected_version)
    reason = _normalized_text(
        reason,
        field="reason",
        maximum=MAX_REASON_LENGTH,
        required=True,
    )
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED
    request_digest = canonical_digest(
        {
            "action": action,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "content_digest": content_digest,
            "edition_name_confirmation": edition_name_confirmation,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            configuration_id=configuration_id,
        )
        replay = _receipt_for_retry(scope, retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=action,
                request_digest=request_digest,
                content_digest=content_digest,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        digest = _require_exact_configuration_digest(
            scope,
            submitted_digest=content_digest,
        )
        _require_exact_source_digest(scope)
        if edition_name_confirmation != scope.edition.name:
            raise _field_error(
                "edition_name_confirmation",
                "Enter the exact current edition name.",
                "registration_setup_edition_confirmation_mismatch",
            )
        if not _review_resolved(scope, digest):
            raise RegistrationConfigurationReviewRequiredError
        issues = _configuration_issues(scope)
        if issues:
            raise RegistrationConfigurationValidationError(issues)
        active_conflict = RegistrationConfiguration.objects.select_for_update().filter(
            edition=scope.edition,
            status=ConfigurationStatus.ACTIVE,
        )
        if active_conflict.exclude(pk=scope.configuration.id).exists():
            raise RegistrationConfigurationActiveConflictError
        resulting_version = current_version + 1
        scope.configuration.status = ConfigurationStatus.ACTIVE
        scope.configuration.activated_at = scope.evaluated_at
        scope.configuration.last_changed_in_setup_version = resulting_version
        scope.configuration.save(
            update_fields=(
                "status",
                "activated_at",
                "last_changed_in_setup_version",
                "updated_at",
            )
        )
        scope.control.aggregate_version = resulting_version
        scope.control.save(update_fields=("aggregate_version", "updated_at"))
        receipt = _append_command_evidence(
            scope=scope,
            action=action,
            change_kind=RegistrationCommandChangeKind.ACTIVATED,
            resulting_version=resulting_version,
            content_digest=digest,
            reason=reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        _require_configuration_command_evidence(
            scope=scope,
            receipt=receipt,
            content_digest=digest,
        )
        if not _review_resolved(scope, digest):
            raise RegistrationSetupStateConflictError
        return RegistrationConfigurationLifecycleResult(
            setup_id=scope.control.id,
            configuration_id=scope.configuration.id,
            receipt_id=receipt.id,
            resulting_version=resulting_version,
            configuration_version=int(scope.configuration.version),
            status=scope.configuration.status,
            content_digest=digest,
            review_resolved=True,
            replayed=False,
        )


__all__ = [
    "RegistrationConfigurationActiveConflictError",
    "RegistrationConfigurationIssue",
    "RegistrationConfigurationLifecycleResult",
    "RegistrationConfigurationPreview",
    "RegistrationConfigurationReviewRequiredError",
    "RegistrationConfigurationValidationError",
    "RegistrationPreviewAnswerValidation",
    "RegistrationPreviewForbiddenEffects",
    "RegistrationPreviewProduct",
    "RegistrationPreviewQuestion",
    "RegistrationPreviewSection",
    "activate_registration_configuration",
    "preview_registration_configuration",
    "review_registration_configuration",
]
