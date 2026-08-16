"""Authorized registration configuration and attendee lifecycle commands."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Max, Prefetch, Q, QuerySet
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    decide,
    resolve_edition_target,
    resolve_owned_target,
    resolve_self_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.effects.services import (
    DomainEventRecord,
    enqueue_event_delivery,
    publish_domain_event,
)
from maru.events.models import EventEdition
from maru.identity.models import Account, AccountRestriction
from maru.identity.services import enforce_not_restricted
from maru.participation.models import Participation
from maru.registration.availability import (
    OCCUPIED_REGISTRATION_STATES,
    assess_product_availability,
)
from maru.registration.commerce import (
    complete_admission_tier_replacement,
    effective_configuration_capacity,
    effective_product_capacity,
    pending_target_capacity_holds,
)
from maru.registration.media import (
    ProcessedImage,
    ReadableUpload,
    copy_media_safety,
    dispose_storage_if_unreferenced,
    media_is_safe,
    process_image,
    record_media_safety,
)
from maru.registration.models import (
    AdmissionProduct,
    AdmissionTierReplacement,
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    CheckInRecord,
    ConfigurationStatus,
    Entitlement,
    MediaReviewStatus,
    MediaSafetyReceipt,
    MinorRegistrationPolicy,
    PaymentAttempt,
    QuestionFieldType,
    QuestionVisibility,
    Registration,
    RegistrationAdjustment,
    RegistrationCommandReceipt,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSubmission,
    RegistrationTemplate,
    RegistrationTemplateProduct,
    RegistrationTemplateQuestion,
    RegistrationTemplateSection,
    RegistrationTimelineEntry,
    TemplateStatus,
)
from maru.registration.profile_choices import (
    MAX_FURSUITS,
    pronoun_display,
)
from maru.registration.profile_policy import (
    COLLECTION_NOTICE_VERSION,
    DIRECTORY_CONSENT_VERSION,
)
from maru.registration.question_conditions import (
    MAX_SIGNED_32_BIT_INTEGER,
    MIN_SIGNED_32_BIT_INTEGER,
    condition_value_is_compatible,
)

MANAGE_CONFIGURATION = "registration.manage_configuration"
REGISTER_SELF = "registration.register_self"
REGISTER_ON_BEHALF = "registration.register_on_behalf"
CHECK_IN = "registration.check_in"
MANAGE_EXCEPTIONS = "registration.manage_exceptions"
MANAGE_FINANCE = "registration.manage_finance"
MANAGE_SELF_PROFILE = "registration.manage_self_profile"
MODERATE_PUBLIC_PROFILE = "registration.moderate_public_profile"
MAX_SHORT_ANSWER_LENGTH = 500
MAX_LONG_ANSWER_LENGTH = 4_000
MAX_MULTIPLE_CHOICE_VALUES = 64
MAX_REGISTRATION_CAPACITY = 1_000_000
MAX_REGISTRATION_DRAFTS_PER_EDITION = 32
MAX_REGISTRATION_SECTIONS = 64
MAX_REGISTRATION_QUESTIONS = 256
MAX_REGISTRATION_PRODUCTS = 128
MAX_REASONABLE_AGE = 120
DEFAULT_ADULT_AGE = 18


@dataclass(frozen=True)
class AttendeeFursuitInput:
    name: str
    species: str
    photo: UploadedFile | None = None
    fursuit_id: UUID | None = None
    reuse_from_id: UUID | None = None
    keep_photo: bool = True


@dataclass(frozen=True)
class AttendeeProfileInput:
    real_name: str
    date_of_birth: date
    address_line_1: str
    address_line_2: str
    locality: str
    postal_code: str
    region: str
    country_code: str
    emergency_contact_name: str
    emergency_contact_phone: str
    phone_number: str
    telegram_handle: str
    pronoun_code: str
    other_pronouns: str
    bio: str
    spoken_language_codes: tuple[str, ...]
    profile_photo: UploadedFile | None
    reuse_profile_photo_id: UUID | None
    keep_profile_photo: bool
    brings_fursuits: bool
    fursuits: tuple[AttendeeFursuitInput, ...]
    directory_visible: bool
    directory_country_code: str = ""
    guardian_name: str = ""
    guardian_email: str = ""
    guardian_relationship: str = ""
    guardian_notice_version: str = ""


@dataclass(frozen=True)
class PublicRegistrationResult:
    account: Account
    registration: Registration
    profile: AttendeeRegistrationProfile
    account_created: bool
    replayed: bool = False
    guardian_consent_required: bool = False
    guardian_test_token: str | None = None


@dataclass(frozen=True, slots=True)
class RegistrationLifecycleResult:
    expired: int = 0
    inactive_cancelled: int = 0
    closed_waitlist_cancelled: int = 0
    promoted: int = 0
    tier_replacements_expired: int = 0


@dataclass(frozen=True, slots=True)
class RegistrationLifecycleCandidates:
    expired: int = 0
    inactive_cancelled: int = 0
    closed_waitlist_cancelled: int = 0

    @property
    def total(self) -> int:
        return self.expired + self.inactive_cancelled + self.closed_waitlist_cancelled


@dataclass(frozen=True, slots=True)
class _LifecycleTransition:
    counter: str
    target_state: str
    adjustment_kind: str
    reason: str
    event_name: str
    timeline_kind: str
    timeline_title: str
    timeline_summary: str
    audit_operation: str
    audit_reason_code: str


def _audit_record(
    *,
    actor: Account,
    capability_code: str,
    operation: str,
    organization_id: UUID | None,
    edition_id: UUID | None,
    target_type: str,
    target_id: UUID | None,
    correlation_id: UUID,
    outcome: str,
    reason_code: str,
    obligations: Iterable[str] = (),
    changed_fields: Iterable[str] = (),
    source_channel: str,
    target_count: int | None = None,
) -> AuditRecord:
    safe_metadata: dict[str, object] = {"policy_version": POLICY_VERSION}
    if target_count is not None:
        safe_metadata["target_count"] = target_count
    return AuditRecord(
        principal_kind="account",
        principal_id=actor.id,
        principal_context_id=None,
        organization_id=organization_id,
        event_edition_id=edition_id,
        capability_code=capability_code,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        reason_code=reason_code,
        correlation_id=correlation_id,
        request_id=correlation_id,
        source_channel=source_channel,
        obligations=tuple(sorted(obligations)),
        changed_fields=tuple(sorted(changed_fields)),
        safe_metadata=safe_metadata,
        retention_class="security-extended",
    )


def _require_decision(
    *,
    actor: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget | None,
    operation: str,
    target_type: str,
    target_id: UUID | None,
    correlation_id: UUID,
    source_channel: str,
) -> frozenset[str]:
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=target,
    )
    if decision.allowed:
        return decision.obligations
    append_audit(
        _audit_record(
            actor=actor,
            capability_code=capability_code,
            operation=operation,
            organization_id=target.organization_id if target is not None else None,
            edition_id=target.edition_id if target is not None else None,
            target_type=target_type,
            target_id=target_id,
            correlation_id=correlation_id,
            outcome=AuditEvent.Outcome.DENY,
            reason_code=decision.reason_code,
            source_channel=source_channel,
        )
    )
    raise AuthorizationDenied(
        "The registration operation is unavailable.",
        reason_code=decision.reason_code,
    )


def _require_reason(reason: str) -> str:
    normalized = reason.strip()
    if not normalized:
        raise ValidationError(
            {"reason": "A reason is required."},
            code="reason_required",
        )
    return normalized


def _question_values(
    question: RegistrationTemplateQuestion | RegistrationQuestion,
) -> dict[str, object]:
    return {
        "key": question.key,
        "label": question.label,
        "help_text": question.help_text,
        "field_type": question.field_type,
        "required": question.required,
        "position": question.position,
        "options": list(question.options),
        "purpose": question.purpose,
        "visibility": question.visibility,
        "classification": question.classification,
        "condition_question_key": question.condition_question_key,
        "condition_value": question.condition_value,
    }


def _question_schema_values(question: RegistrationQuestion) -> dict[str, object]:
    values = _question_values(question)
    values["section"] = (
        {
            "key": question.section.key,
            "title": question.section.title,
            "description": question.section.description,
            "position": question.section.position,
        }
        if question.section_id is not None and question.section is not None
        else None
    )
    return values


def _product_values(
    product: RegistrationTemplateProduct | AdmissionProduct,
) -> dict[str, object]:
    return {
        "code": product.code,
        "name": product.name,
        "description": product.description,
        "price_minor": product.price_minor,
        "capacity": product.capacity,
        "position": product.position,
        "entitlement_code": product.entitlement_code,
        "entitlement_name": product.entitlement_name,
        "sales_open_at": product.sales_open_at,
        "sales_close_at": product.sales_close_at,
        "required_capacity_codes": list(product.required_capacity_codes),
        "eligibility_explanation": product.eligibility_explanation,
        "waitlist_enabled": product.waitlist_enabled,
        "payment_window_minutes": product.payment_window_minutes,
    }


def _section_values(
    section: RegistrationTemplateSection | RegistrationSection,
) -> dict[str, object]:
    return {
        "key": section.key,
        "title": section.title,
        "description": section.description,
        "position": section.position,
    }


def _configuration_source_kind(configuration: RegistrationConfiguration) -> str:
    if configuration.source_template_id is not None:
        return "template"
    if configuration.source_edition_id is not None:
        return "edition"
    return "blank"


def _query_limit_exceeded(queryset: QuerySet[Any], *, limit: int) -> bool:
    return (
        queryset.order_by("id").values_list("id", flat=True)[limit : limit + 1].exists()
    )


def _validate_configuration_collection_limits(
    configuration: RegistrationConfiguration | RegistrationTemplate,
) -> None:
    collection_limits = (
        (configuration.sections.all(), MAX_REGISTRATION_SECTIONS, "sections"),
        (configuration.questions.all(), MAX_REGISTRATION_QUESTIONS, "questions"),
        (configuration.products.all(), MAX_REGISTRATION_PRODUCTS, "products"),
    )
    for queryset, limit, collection_name in collection_limits:
        if _query_limit_exceeded(queryset, limit=limit):
            raise ValidationError(
                {
                    collection_name: ValidationError(
                        (
                            f"Registration setup supports at most {limit} "
                            f"{collection_name}."
                        ),
                        code="registration_setup_limit_exceeded",
                    )
                },
            )


def create_configuration_draft(  # noqa: PLR0915
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    name: str,
    correlation_id: UUID,
    reason: str,
    source_template_id: UUID | None = None,
    source_edition_id: UUID | None = None,
    opens_at: datetime | None = None,
    closes_at: datetime | None = None,
    capacity: int | None = None,
    currency: str | None = None,
    minimum_age: int | None = None,
    default_payment_window_minutes: int | None = None,
    waitlist_enabled: bool | None = None,
    automatic_waitlist_promotion: bool | None = None,
    source_channel: str = "service",
) -> RegistrationConfiguration:
    """Create one independent draft from nothing, a template, or another edition."""

    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_CONFIGURATION,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.configuration.create_draft",
        target_type="registration.configuration",
        target_id=None,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    normalized_reason = _require_reason(reason)
    if source_template_id is not None and source_edition_id is not None:
        raise ValidationError(
            "Choose one registration configuration source.",
            code="multiple_configuration_sources",
        )

    with transaction.atomic():
        edition = EventEdition.objects.select_for_update().get(
            id=edition_id,
            organization_id=organization_id,
        )
        if edition.lifecycle in {
            EventEdition.Lifecycle.ARCHIVED,
            EventEdition.Lifecycle.CANCELLED,
        }:
            raise ValidationError(
                "Registration configuration is closed for this edition.",
                code="edition_registration_closed",
            )
        latest_version = (
            RegistrationConfiguration.objects.filter(edition=edition).aggregate(
                maximum=Max("version")
            )["maximum"]
            or 0
        )
        if _query_limit_exceeded(
            RegistrationConfiguration.objects.filter(
                edition=edition,
                status=ConfigurationStatus.DRAFT,
            ),
            # Reject creation when the 32nd existing draft is present; the
            # requested command would otherwise create a 33rd.
            limit=MAX_REGISTRATION_DRAFTS_PER_EDITION - 1,
        ):
            raise ValidationError(
                {
                    "edition": ValidationError(
                        (
                            "Registration setup supports at most "
                            f"{MAX_REGISTRATION_DRAFTS_PER_EDITION} drafts per "
                            "edition."
                        ),
                        code="registration_setup_limit_exceeded",
                    )
                },
            )

        question_source: Iterable[
            RegistrationTemplateQuestion | RegistrationQuestion
        ] = ()
        section_source: Iterable[RegistrationTemplateSection | RegistrationSection] = ()
        product_source: Iterable[RegistrationTemplateProduct | AdmissionProduct] = ()
        source_template: RegistrationTemplate | None = None
        source_edition: EventEdition | None = None
        source_configuration: RegistrationConfiguration | None = None
        source_kind = "blank"

        if source_template_id is not None:
            source_template = RegistrationTemplate.objects.select_for_update().get(
                id=source_template_id,
                organization_id=organization_id,
                status=TemplateStatus.PUBLISHED,
            )
            _validate_configuration_collection_limits(source_template)
            if (
                source_template.series_id is not None
                and source_template.series_id != edition.series_id
            ):
                raise ValidationError(
                    "This template is limited to another convention series.",
                    code="template_series_mismatch",
                )
            question_source = source_template.questions.all()
            section_source = source_template.sections.all()
            product_source = source_template.products.all()
            source_kind = "template"
        elif source_edition_id is not None:
            source_edition = EventEdition.objects.get(
                id=source_edition_id,
                organization_id=organization_id,
            )
            source_configuration = (
                RegistrationConfiguration.objects.filter(
                    organization_id=organization_id,
                    edition_id=source_edition_id,
                    status__in=(
                        ConfigurationStatus.ACTIVE,
                        ConfigurationStatus.RETIRED,
                    ),
                )
                .order_by("-version")
                .first()
            )
            if source_configuration is None:
                raise ValidationError(
                    "The source edition has no reusable registration version.",
                    code="source_configuration_unavailable",
                )
            _validate_configuration_collection_limits(source_configuration)
            question_source = source_configuration.questions.all()
            section_source = source_configuration.sections.all()
            product_source = source_configuration.products.all()
            source_kind = "edition"

        inherited = source_template is not None or source_configuration is not None
        source_values = source_template or source_configuration
        resolved_opens_at = opens_at or getattr(source_values, "opens_at", None)
        resolved_closes_at = closes_at or getattr(source_values, "closes_at", None)
        resolved_capacity = (
            capacity
            if capacity is not None
            else getattr(source_values, "capacity", None)
        )
        resolved_currency = (
            currency
            if currency is not None
            else getattr(source_values, "currency", None)
        )
        resolved_minimum_age = (
            minimum_age
            if minimum_age is not None
            else int(getattr(source_values, "minimum_age", 18))
        )
        resolved_payment_window = (
            default_payment_window_minutes
            if default_payment_window_minutes is not None
            else int(getattr(source_values, "default_payment_window_minutes", 24 * 60))
        )
        resolved_waitlist_enabled = (
            waitlist_enabled
            if waitlist_enabled is not None
            else bool(getattr(source_values, "waitlist_enabled", True))
        )
        resolved_automatic_promotion = (
            automatic_waitlist_promotion
            if automatic_waitlist_promotion is not None
            else bool(getattr(source_values, "automatic_waitlist_promotion", True))
        )
        if (
            resolved_opens_at is None
            or resolved_closes_at is None
            or resolved_capacity is None
            or resolved_currency is None
        ):
            raise ValidationError(
                "A blank registration draft needs opening, closing, capacity, "
                "and currency values.",
                code="configuration_defaults_required",
            )
        if (
            isinstance(resolved_capacity, bool)
            or not isinstance(resolved_capacity, int)
            or not 1 <= resolved_capacity <= MAX_REGISTRATION_CAPACITY
        ):
            raise ValidationError(
                {
                    "capacity": (
                        "Registration capacity must be between 1 and "
                        f"{MAX_REGISTRATION_CAPACITY}."
                    )
                },
                code="registration_capacity_out_of_range",
            )

        configuration = RegistrationConfiguration.objects.create(
            organization=edition.organization,
            edition=edition,
            name=name.strip() or f"{edition.name} registration",
            version=latest_version + 1,
            source_template=source_template,
            source_edition=source_edition,
            review_required=True,
            review_note=(
                f"Inherited from {source_kind}; review required. "
                f"Creation reason: {normalized_reason}"
                if inherited
                else f"New blank draft. Creation reason: {normalized_reason}"
            ),
            opens_at=resolved_opens_at,
            closes_at=resolved_closes_at,
            capacity=resolved_capacity,
            currency=resolved_currency,
            minimum_age=resolved_minimum_age,
            default_payment_window_minutes=resolved_payment_window,
            waitlist_enabled=resolved_waitlist_enabled,
            automatic_waitlist_promotion=resolved_automatic_promotion,
            created_by_id=actor.id,
        )
        section_map: dict[UUID, RegistrationSection] = {}
        for source_section in section_source:
            copied_section = RegistrationSection.objects.create(
                configuration=configuration,
                **_section_values(source_section),
            )
            section_map[source_section.id] = copied_section
        RegistrationQuestion.objects.bulk_create(
            [
                RegistrationQuestion(
                    configuration=configuration,
                    section=(
                        section_map.get(question.section_id)
                        if question.section_id is not None
                        else None
                    ),
                    **_question_values(question),
                )
                for question in question_source
            ]
        )
        AdmissionProduct.objects.bulk_create(
            [
                AdmissionProduct(
                    configuration=configuration,
                    **_product_values(product),
                )
                for product in product_source
            ]
        )
        audit_event = append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_CONFIGURATION,
                operation="registration.configuration.create_draft",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.configuration",
                target_id=configuration.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="configuration_draft_created",
                obligations=obligations,
                changed_fields=(
                    "configuration",
                    "sections",
                    "questions",
                    "products",
                    "provenance",
                ),
                source_channel=source_channel,
            )
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="registration.configuration.draft_created.v1",
                schema_version=1,
                organization_id=organization_id,
                event_edition_id=edition_id,
                aggregate_type="registration.configuration",
                aggregate_id=configuration.id,
                aggregate_version=1,
                payload={
                    "configuration_version": str(configuration.version),
                    "source_kind": source_kind,
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="registration-configuration",
            ),
            workload_pool="core",
        )
        return configuration


def _validate_configuration_question_graph(
    questions: Iterable[RegistrationQuestion],
) -> None:
    """Prove every conditional edge is ordered, visible, and satisfiable."""

    prior_questions: dict[str, RegistrationQuestion] = {}
    for question in questions:
        source_key = question.condition_question_key
        if not source_key:
            prior_questions[question.key] = question
            continue
        source = prior_questions.get(source_key)
        if source is None or source.position >= question.position:
            raise ValidationError(
                {
                    "questions": (
                        f"Conditional question {question.key} must depend on an "
                        "earlier question."
                    )
                },
                code="registration_condition_source_not_prior",
            )
        if (
            question.visibility == QuestionVisibility.ATTENDEE_AND_STAFF
            and source.visibility == QuestionVisibility.REGISTRATION_STAFF
        ):
            raise ValidationError(
                {
                    "questions": (
                        f"Attendee question {question.key} cannot depend on a "
                        "staff-only question."
                    )
                },
                code="registration_condition_visibility_incompatible",
            )
        if not condition_value_is_compatible(
            field_type=source.field_type,
            options=source.options,
            value=question.condition_value,
        ):
            raise ValidationError(
                {
                    "questions": (
                        f"Conditional value for {question.key} cannot be produced "
                        f"by {source.key}."
                    )
                },
                code="registration_condition_value_incompatible",
            )
        prior_questions[question.key] = question


def activate_configuration(
    *,
    organization_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> RegistrationConfiguration:
    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_CONFIGURATION,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.configuration.activate",
        target_type="registration.configuration",
        target_id=configuration_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    normalized_reason = _require_reason(reason)
    with transaction.atomic():
        EventEdition.objects.select_for_update().get(
            id=edition_id,
            organization_id=organization_id,
        )
        configuration = RegistrationConfiguration.objects.select_for_update().get(
            id=configuration_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if configuration.status != ConfigurationStatus.DRAFT:
            raise ValidationError(
                "Only a draft registration version can be activated.",
                code="configuration_not_draft",
            )
        _validate_configuration_collection_limits(configuration)
        _validate_configuration_question_graph(configuration.questions.all())
        products = list(configuration.products.all())
        if not products:
            raise ValidationError(
                "Add at least one admission product before activation.",
                code="registration_products_required",
            )
        if any(product.capacity > configuration.capacity for product in products):
            raise ValidationError(
                "A product capacity cannot exceed the edition registration capacity.",
                code="product_capacity_exceeds_configuration",
            )
        if any(
            product.sales_open_at is not None
            and product.sales_open_at < configuration.opens_at
            for product in products
        ):
            raise ValidationError(
                "Product sales cannot open before the registration period.",
                code="product_sales_before_registration",
            )
        if any(
            product.sales_close_at is not None
            and product.sales_close_at > configuration.closes_at
            for product in products
        ):
            raise ValidationError(
                "Product sales cannot close after the registration period.",
                code="product_sales_after_registration",
            )
        if configuration.minimum_age < DEFAULT_ADULT_AGE:
            policy = getattr(configuration, "minor_policy", None)
            if policy is None or not policy.enabled:
                raise ValidationError(
                    "A reviewed guardian policy is required below the adult age.",
                    code="minor_policy_required",
                )

        now = timezone.now()
        RegistrationConfiguration.objects.filter(
            edition_id=edition_id,
            status=ConfigurationStatus.ACTIVE,
        ).update(
            status=ConfigurationStatus.RETIRED,
            updated_at=now,
        )
        configuration.status = ConfigurationStatus.ACTIVE
        configuration.review_required = False
        configuration.review_note = normalized_reason
        configuration.activated_at = now
        configuration.save(
            update_fields=(
                "status",
                "review_required",
                "review_note",
                "activated_at",
                "updated_at",
            )
        )
        source_kind = _configuration_source_kind(configuration)
        audit_event = append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_CONFIGURATION,
                operation="registration.configuration.activate",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.configuration",
                target_id=configuration.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="configuration_activated",
                obligations=obligations,
                changed_fields=(
                    "status",
                    "review_required",
                    "review_note",
                    "activated_at",
                ),
                source_channel=source_channel,
            )
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="registration.configuration.activated.v1",
                schema_version=1,
                organization_id=organization_id,
                event_edition_id=edition_id,
                aggregate_type="registration.configuration",
                aggregate_id=configuration.id,
                aggregate_version=2,
                payload={
                    "configuration_version": str(configuration.version),
                    "source_kind": source_kind,
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="registration-configuration",
            ),
            workload_pool="core",
        )
        return configuration


def publish_configuration_as_template(
    *,
    organization_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    actor: Account,
    code: str,
    name: str,
    description: str,
    series_limited: bool,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> RegistrationTemplate:
    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_CONFIGURATION,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.template.publish",
        target_type="registration.configuration",
        target_id=configuration_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    _require_reason(reason)
    normalized_code = code.strip().lower()
    with transaction.atomic():
        configuration = (
            RegistrationConfiguration.objects.select_for_update()
            .select_related("edition")
            .prefetch_related("sections", "questions", "products")
            .get(
                id=configuration_id,
                organization_id=organization_id,
                edition_id=edition_id,
                status=ConfigurationStatus.ACTIVE,
            )
        )
        latest_version = (
            RegistrationTemplate.objects.filter(
                organization_id=organization_id,
                code__iexact=normalized_code,
            ).aggregate(maximum=Max("version"))["maximum"]
            or 0
        )
        template = RegistrationTemplate.objects.create(
            organization_id=organization_id,
            series=configuration.edition.series if series_limited else None,
            code=normalized_code,
            name=name.strip(),
            description=description.strip(),
            version=latest_version + 1,
            created_by_id=actor.id,
        )
        section_map: dict[UUID, RegistrationTemplateSection] = {}
        for section in configuration.sections.all():
            copied_section = RegistrationTemplateSection.objects.create(
                template=template,
                **_section_values(section),
            )
            section_map[section.id] = copied_section
        for question in configuration.questions.all():
            RegistrationTemplateQuestion.objects.create(
                template=template,
                section=(
                    section_map.get(question.section_id)
                    if question.section_id is not None
                    else None
                ),
                **_question_values(question),
            )
        for product in configuration.products.all():
            RegistrationTemplateProduct.objects.create(
                template=template,
                **_product_values(product),
            )
        template.status = TemplateStatus.PUBLISHED
        template.published_at = timezone.now()
        template.save(update_fields=("status", "published_at", "updated_at"))
        audit_event = append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_CONFIGURATION,
                operation="registration.template.publish",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.template",
                target_id=template.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="registration_template_published",
                obligations=obligations,
                changed_fields=("template", "sections", "questions", "products"),
                source_channel=source_channel,
            )
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="registration.template.published.v1",
                schema_version=1,
                organization_id=organization_id,
                event_edition_id=edition_id,
                aggregate_type="registration.template",
                aggregate_id=template.id,
                aggregate_version=template.version,
                payload={
                    "template_code": template.code,
                    "template_version": str(template.version),
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="registration-configuration",
            ),
            workload_pool="core",
        )
        return template


def _normalized_condition_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return ""


def _normalize_answer(question: RegistrationQuestion, value: object) -> object:
    if question.field_type in {
        QuestionFieldType.SHORT_TEXT,
        QuestionFieldType.LONG_TEXT,
    }:
        if not isinstance(value, str):
            raise ValidationError(
                {question.key: "Enter text for this question."},
                code="invalid_registration_answer",
            )
        normalized = value.strip()
        maximum = (
            MAX_LONG_ANSWER_LENGTH
            if question.field_type == QuestionFieldType.LONG_TEXT
            else MAX_SHORT_ANSWER_LENGTH
        )
        if len(normalized) > maximum:
            raise ValidationError(
                {question.key: f"Use no more than {maximum} characters."},
                code="registration_answer_too_long",
            )
        return normalized
    if question.field_type == QuestionFieldType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValidationError(
                {question.key: "Choose yes or no."},
                code="invalid_registration_answer",
            )
        return value
    if question.field_type == QuestionFieldType.INTEGER:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationError(
                {question.key: "Enter a whole number."},
                code="invalid_registration_answer",
            )
        if not MIN_SIGNED_32_BIT_INTEGER <= value <= MAX_SIGNED_32_BIT_INTEGER:
            raise ValidationError(
                {question.key: "Enter a signed 32-bit whole number."},
                code="registration_integer_answer_out_of_range",
            )
        return value
    if question.field_type == QuestionFieldType.SINGLE_CHOICE:
        if not isinstance(value, str) or value not in question.options:
            raise ValidationError(
                {question.key: "Choose one of the available options."},
                code="invalid_registration_answer",
            )
        return value
    if question.field_type == QuestionFieldType.MULTIPLE_CHOICE:
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
            or len(value) > MAX_MULTIPLE_CHOICE_VALUES
            or len(set(value)) != len(value)
            or any(item not in question.options for item in value)
        ):
            raise ValidationError(
                {question.key: "Choose only available options without duplicates."},
                code="invalid_registration_answer",
            )
        return value
    raise ValidationError(
        {question.key: "This question type is unavailable."},
        code="unsupported_registration_question",
    )


def validate_registration_answers(
    *,
    questions: Iterable[RegistrationQuestion],
    answers: object,
    include_staff_questions: bool = False,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if not isinstance(answers, dict) or any(
        not isinstance(key, str) for key in answers
    ):
        raise ValidationError(
            {"answers": "Registration answers must be an object."},
            code="invalid_registration_answers",
        )
    question_list = [
        question
        for question in questions
        if include_staff_questions
        or question.visibility == QuestionVisibility.ATTENDEE_AND_STAFF
    ]
    known_keys = {question.key for question in question_list}
    unknown_keys = set(answers).difference(known_keys)
    if unknown_keys:
        raise ValidationError(
            {"answers": f"Unknown registration question: {sorted(unknown_keys)[0]}"},
            code="unknown_registration_question",
        )

    normalized: dict[str, object] = {}
    schema: list[dict[str, object]] = []
    for question in question_list:
        active = True
        if question.condition_question_key:
            active = (
                _normalized_condition_value(
                    normalized.get(question.condition_question_key)
                )
                == question.condition_value
            )
        schema.append(_question_schema_values(question))
        if not active:
            if question.key in answers:
                raise ValidationError(
                    {
                        question.key: (
                            "This question is not applicable to the current answers."
                        )
                    },
                    code="inactive_registration_question",
                )
            continue
        if question.key not in answers:
            if question.required:
                raise ValidationError(
                    {question.key: "This question is required."},
                    code="required_registration_answer",
                )
            continue
        value = _normalize_answer(question, answers[question.key])
        if question.required and value in ("", []):
            raise ValidationError(
                {question.key: "This question is required."},
                code="required_registration_answer",
            )
        normalized[question.key] = value
    return normalized, schema


def _normalize_profile_extension_value(  # noqa: PLR0912
    field: RegistrationProfileExtensionField,
    value: object,
) -> object:
    if value is None:
        if field.field_type in {
            QuestionFieldType.BOOLEAN,
            QuestionFieldType.INTEGER,
            QuestionFieldType.SINGLE_CHOICE,
        }:
            return None
        raise ValidationError(
            {"value": "Use the field's typed empty value."},
            code="invalid_profile_extension_clear_value",
        )
    if field.field_type in {
        QuestionFieldType.SHORT_TEXT,
        QuestionFieldType.LONG_TEXT,
    }:
        if not isinstance(value, str):
            raise ValidationError(
                {"value": "Enter text for this profile field."},
                code="invalid_profile_extension_value",
            )
        normalized = value.strip()
        maximum = (
            MAX_LONG_ANSWER_LENGTH
            if field.field_type == QuestionFieldType.LONG_TEXT
            else MAX_SHORT_ANSWER_LENGTH
        )
        if len(normalized) > maximum:
            raise ValidationError(
                {"value": f"Use no more than {maximum} characters."},
                code="profile_extension_value_too_long",
            )
        return normalized
    if field.field_type == QuestionFieldType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValidationError(
                {"value": "Choose yes or no."},
                code="invalid_profile_extension_value",
            )
        return value
    if field.field_type == QuestionFieldType.INTEGER:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationError(
                {"value": "Enter a whole number."},
                code="invalid_profile_extension_value",
            )
        if not MIN_SIGNED_32_BIT_INTEGER <= value <= MAX_SIGNED_32_BIT_INTEGER:
            raise ValidationError(
                {"value": "Enter a signed 32-bit whole number."},
                code="profile_extension_integer_out_of_range",
            )
        return value
    if field.field_type == QuestionFieldType.SINGLE_CHOICE:
        if not isinstance(value, str) or value not in field.options:
            raise ValidationError(
                {"value": "Choose one of the available options."},
                code="invalid_profile_extension_value",
            )
        return value
    if field.field_type == QuestionFieldType.MULTIPLE_CHOICE:
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
            or len(value) > MAX_MULTIPLE_CHOICE_VALUES
            or len(set(value)) != len(value)
            or any(item not in field.options for item in value)
        ):
            raise ValidationError(
                {"value": "Choose only available options without duplicates."},
                code="invalid_profile_extension_value",
            )
        return value
    raise ValidationError(
        {"value": "This profile field type is unavailable."},
        code="unsupported_profile_extension_field",
    )


def _append_timeline(
    *,
    registration: Registration,
    kind: str,
    title: str,
    summary: str,
    occurred_at: datetime,
    actor_kind: str,
    actor_id: UUID | None,
    correlation_id: UUID,
    audience: str = RegistrationTimelineEntry.Audience.ATTENDEE_AND_STAFF,
) -> RegistrationTimelineEntry:
    latest_sequence = (
        RegistrationTimelineEntry.objects.filter(registration=registration).aggregate(
            maximum=Max("sequence")
        )["maximum"]
        or 0
    )
    return RegistrationTimelineEntry.objects.create(
        registration=registration,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        sequence=latest_sequence + 1,
        kind=kind,
        title=title,
        summary=summary,
        audience=audience,
        occurred_at=occurred_at,
        actor_kind=actor_kind,
        actor_id=actor_id,
        correlation_id=correlation_id,
    )


def _grant_product_entitlement(
    *,
    registration: Registration,
    granted_at: datetime,
) -> Entitlement:
    return Entitlement.objects.create(
        registration=registration,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        code=registration.product.entitlement_code,
        label_snapshot=registration.product.entitlement_name,
        granted_at=granted_at,
    )


def _payment_deadline(
    *,
    configuration: RegistrationConfiguration,
    product: AdmissionProduct,
    starts_at: datetime,
) -> datetime:
    minutes = (
        product.payment_window_minutes
        if product.payment_window_minutes is not None
        else configuration.default_payment_window_minutes
    )
    return starts_at + timedelta(minutes=minutes)


def _record_adjustment(
    *,
    registration: Registration,
    kind: str,
    reason: str,
    occurred_at: datetime,
    actor_kind: str,
    actor_id: UUID | None,
    from_state: str = "",
    to_state: str = "",
    previous_deadline: datetime | None = None,
    new_deadline: datetime | None = None,
    amount_minor: int | None = None,
) -> RegistrationAdjustment:
    return RegistrationAdjustment.objects.create(
        registration=registration,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        kind=kind,
        from_state=from_state,
        to_state=to_state,
        previous_deadline=previous_deadline,
        new_deadline=new_deadline,
        amount_minor=amount_minor,
        currency=registration.currency_snapshot if amount_minor is not None else "",
        actor_kind=actor_kind,
        actor_id=actor_id,
        reason=reason,
        occurred_at=occurred_at,
    )


def _publish_registration_transition(
    *,
    registration: Registration,
    event_name: str,
    from_state: str,
    correlation_id: UUID,
    actor_kind: str,
    actor_id: UUID | None,
    causation_id: UUID | None = None,
    workload_pool: str = "core",
) -> None:
    event, _ = publish_domain_event(
        DomainEventRecord(
            event_name=event_name,
            schema_version=1,
            organization_id=registration.organization_id,
            event_edition_id=registration.edition_id,
            aggregate_type="registration.registration",
            aggregate_id=registration.id,
            aggregate_version=registration.aggregate_version,
            payload={
                "from_state": from_state,
                "to_state": registration.state,
                "reference": registration.reference,
            },
            correlation_id=correlation_id,
            causation_id=causation_id,
            actor_kind=actor_kind,
            actor_id=actor_id,
            retention_class="registration-operational",
        ),
        workload_pool=workload_pool,
    )
    if event_name in {
        "registration.payment.reconciled.v1",
        "registration.payment.deadline_changed.v1",
        "registration.payment.waived.v1",
        "registration.payment.expired.v1",
        "registration.waitlist.offered.v1",
        "registration.cancelled.v1",
        "registration.checked_in.v1",
        "registration.guardian.accepted.v1",
    }:
        enqueue_event_delivery(
            event=event,
            destination="notifications",
            workload_pool="notifications",
        )


def _system_audit(
    *,
    registration: Registration,
    operation: str,
    reason_code: str,
    correlation_id: UUID,
    changed_fields: Iterable[str],
) -> AuditEvent:
    return append_audit(
        AuditRecord(
            principal_kind="workload",
            principal_id=None,
            principal_context_id=None,
            organization_id=registration.organization_id,
            event_edition_id=registration.edition_id,
            capability_code="registration.lifecycle.process",
            operation=operation,
            target_type="registration.registration",
            target_id=registration.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=None,
            source_channel="worker",
            obligations=("audit",),
            changed_fields=tuple(sorted(changed_fields)),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="security-extended",
        )
    )


def submit_registration(
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    subject_account: Account | None = None,
    product_id: UUID,
    answers: object,
    correlation_id: UUID,
    source_channel: str = "api",
    now: datetime | None = None,
    allow_unverified: bool = False,
    requires_guardian_consent: bool = False,
    bypass_sale_windows: bool = False,
    staff_reason: str = "",
) -> Registration:
    subject = subject_account or actor
    staff_assisted = subject_account is not None
    normalized_staff_reason = _require_reason(staff_reason) if staff_assisted else ""
    if not subject.is_active:
        raise ValidationError(
            "This account cannot start or change a registration.",
            code="registration_account_inactive",
        )
    if not subject.has_verified_email and not allow_unverified:
        raise ValidationError(
            "Verify your email before registration can reserve a place.",
            code="registration_email_not_verified",
        )
    enforce_not_restricted(
        account=subject,
        organization_id=organization_id,
        edition_id=edition_id,
        kind=AccountRestriction.Kind.REGISTRATION,
    )
    capability_code = REGISTER_ON_BEHALF if staff_assisted else REGISTER_SELF
    authorization_target = (
        resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if staff_assisted
        else resolve_self_target(
            principal=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    )
    obligations = _require_decision(
        actor=actor,
        capability_code=capability_code,
        target=authorization_target,
        operation=(
            "registration.submit_on_behalf" if staff_assisted else "registration.submit"
        ),
        target_type="registration.registration",
        target_id=None,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    submitted_at = now or timezone.now()
    with transaction.atomic():
        participation = Participation.objects.select_for_update().get(
            organization_id=organization_id,
            edition_id=edition_id,
            account=subject,
        )
        configuration = (
            RegistrationConfiguration.objects.select_for_update()
            .prefetch_related("questions")
            .get(
                organization_id=organization_id,
                edition_id=edition_id,
                status=ConfigurationStatus.ACTIVE,
            )
        )
        if (
            not bypass_sale_windows
            and not configuration.opens_at <= submitted_at < configuration.closes_at
        ):
            raise ValidationError(
                "Registration is not open at this time.",
                code="registration_not_open",
            )
        if Registration.objects.filter(
            edition_id=edition_id,
            account=subject,
        ).exists():
            raise ValidationError(
                "This account already has a registration for the edition.",
                code="registration_already_exists",
            )
        product = AdmissionProduct.objects.select_for_update().get(
            id=product_id,
            configuration=configuration,
            status=AdmissionProduct.Status.AVAILABLE,
        )
        product_count = Registration.objects.filter(
            product=product,
            state__in=OCCUPIED_REGISTRATION_STATES,
        ).count()
        total_count = Registration.objects.filter(
            configuration=configuration,
            state__in=OCCUPIED_REGISTRATION_STATES,
        ).count()
        availability = assess_product_availability(
            product=product,
            account=subject,
            at=submitted_at,
            ignore_sale_window=bypass_sale_windows,
        )
        if not availability.selectable:
            raise ValidationError(
                availability.explanation,
                code=availability.code,
            )
        normalized_answers, schema = validate_registration_answers(
            questions=configuration.questions.all(),
            answers=answers,
            include_staff_questions=subject_account is not None,
        )
        registration_id = uuid4()
        capacity_reached = product_count + pending_target_capacity_holds(
            product, at=submitted_at
        ) >= effective_product_capacity(
            product
        ) or total_count >= effective_configuration_capacity(configuration)
        if requires_guardian_consent:
            state = Registration.State.GUARDIAN_PENDING
        elif capacity_reached:
            state = Registration.State.WAITLISTED
        elif product.price_minor == 0:
            state = Registration.State.CONFIRMED
        else:
            state = Registration.State.PAYMENT_PENDING
        payment_due_at = (
            _payment_deadline(
                configuration=configuration,
                product=product,
                starts_at=submitted_at,
            )
            if state == Registration.State.PAYMENT_PENDING
            else None
        )
        registration = Registration.objects.create(
            id=registration_id,
            organization_id=organization_id,
            edition_id=edition_id,
            participation=participation,
            account=subject,
            configuration=configuration,
            product=product,
            reference=f"REG-{registration_id.hex[:10].upper()}",
            state=state,
            aggregate_version=1,
            product_name_snapshot=product.name,
            price_minor_snapshot=product.price_minor,
            currency_snapshot=configuration.currency,
            submitted_at=submitted_at,
            waitlisted_at=(
                submitted_at if state == Registration.State.WAITLISTED else None
            ),
            payment_due_at=payment_due_at,
            confirmed_at=(
                submitted_at if state == Registration.State.CONFIRMED else None
            ),
            confirmation_basis=(
                Registration.ConfirmationBasis.FREE
                if state == Registration.State.CONFIRMED
                else ""
            ),
            submission_source=(
                Registration.SubmissionSource.STAFF_ASSISTED
                if staff_assisted
                else Registration.SubmissionSource.SELF
            ),
            submitted_by=actor if staff_assisted else None,
            staff_submission_reason=normalized_staff_reason,
        )
        RegistrationSubmission.objects.create(
            registration=registration,
            organization_id=organization_id,
            edition_id=edition_id,
            configuration_version=configuration.version,
            schema_snapshot=schema,
            answers=normalized_answers,
            submitted_at=submitted_at,
        )
        _append_timeline(
            registration=registration,
            kind="registration_submitted",
            title="Registration submitted",
            summary=(
                (
                    "Convention staff created this registration for you. "
                    if staff_assisted
                    else ""
                )
                + f"{product.name} selected. "
                + (
                    ("Guardian consent is required before a place can be reserved.")
                    if state == Registration.State.GUARDIAN_PENDING
                    else (
                        "You joined the waitlist. Payment is requested only if "
                        "a place is offered."
                    )
                    if state == Registration.State.WAITLISTED
                    else "Payment is the next step."
                    if state == Registration.State.PAYMENT_PENDING
                    else "No payment is required."
                )
            ),
            occurred_at=submitted_at,
            actor_kind="account",
            actor_id=actor.id,
            correlation_id=correlation_id,
        )
        if staff_assisted:
            _append_timeline(
                registration=registration,
                kind="staff_assisted_registration",
                title="Staff-assisted registration evidence",
                summary=normalized_staff_reason,
                occurred_at=submitted_at,
                actor_kind="account",
                actor_id=actor.id,
                correlation_id=correlation_id,
                audience=RegistrationTimelineEntry.Audience.STAFF_ONLY,
            )
        if state == Registration.State.CONFIRMED:
            _grant_product_entitlement(
                registration=registration,
                granted_at=submitted_at,
            )
            _append_timeline(
                registration=registration,
                kind="registration_confirmed",
                title="Registration confirmed",
                summary="The admission entitlement is active.",
                occurred_at=submitted_at,
                actor_kind="system",
                actor_id=None,
                correlation_id=correlation_id,
            )
        elif state == Registration.State.WAITLISTED:
            _append_timeline(
                registration=registration,
                kind="waitlist_joined",
                title="Added to the waitlist",
                summary=(
                    "No payment is due now. Maru will set a fresh payment deadline "
                    "if a place becomes available."
                ),
                occurred_at=submitted_at,
                actor_kind="system",
                actor_id=None,
                correlation_id=correlation_id,
            )
        audit_event = append_audit(
            _audit_record(
                actor=actor,
                capability_code=capability_code,
                operation=(
                    "registration.submit_on_behalf"
                    if staff_assisted
                    else "registration.submit"
                ),
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.registration",
                target_id=registration.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=(
                    "staff_assisted_registration"
                    if staff_assisted
                    else "self_relationship"
                ),
                obligations=obligations,
                changed_fields=(
                    "registration",
                    "staff_assistance" if staff_assisted else "self_submission",
                    "submission",
                    "timeline",
                ),
                source_channel=source_channel,
            )
        )
        submitted_event, _ = publish_domain_event(
            DomainEventRecord(
                event_name="registration.submitted.v1",
                schema_version=1,
                organization_id=organization_id,
                event_edition_id=edition_id,
                aggregate_type="registration.registration",
                aggregate_id=registration.id,
                aggregate_version=registration.aggregate_version,
                payload={
                    "from_state": "none",
                    "to_state": registration.state,
                    "reference": registration.reference,
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="registration-operational",
            ),
            workload_pool="core",
        )
        enqueue_event_delivery(
            event=submitted_event,
            destination="notifications",
            workload_pool="notifications",
        )
        return registration


def submit_public_registration(  # noqa: PLR0912, PLR0915
    *,
    organization_id: UUID,
    edition_id: UUID,
    product_id: UUID,
    answers: object,
    profile_input: AttendeeProfileInput,
    correlation_id: UUID,
    account: Account | None = None,
    email: str = "",
    display_name: str = "",
    password: str = "",
    now: datetime | None = None,
    source_channel: str = "public_web",
    idempotency_key: UUID | None = None,
    request_digest: str = "",
    expected_configuration_version: int | None = None,
    staff_actor: Account | None = None,
    staff_reason: str = "",
    bypass_sale_windows: bool = False,
) -> PublicRegistrationResult:
    """Create public account/participation context and submit one registration."""

    submitted_at = now or timezone.now()
    with transaction.atomic():
        configuration = (
            RegistrationConfiguration.objects.select_for_update()
            .select_related("edition")
            .get(
                organization_id=organization_id,
                edition_id=edition_id,
                status=ConfigurationStatus.ACTIVE,
            )
        )
        if (
            expected_configuration_version is not None
            and configuration.version != expected_configuration_version
        ):
            raise ValidationError(
                "Registration changed after the form was loaded. Review it again.",
                code="registration_configuration_changed",
            )
        if idempotency_key is not None:
            receipt = (
                RegistrationCommandReceipt.objects.select_for_update()
                .select_related(
                    "registration",
                    "account",
                )
                .filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    account=account,
                    idempotency_key=idempotency_key,
                )
                .first()
            )
            if receipt is not None:
                if receipt.request_digest != request_digest:
                    raise ValidationError(
                        "The idempotency key was already used for another request.",
                        code="registration_idempotency_conflict",
                    )
                return PublicRegistrationResult(
                    account=receipt.account,
                    registration=receipt.registration,
                    profile=receipt.registration.attendee_profile,
                    account_created=False,
                    replayed=True,
                )
        relevant_date = configuration.edition.starts_on
        birth_date = profile_input.date_of_birth
        age = (
            relevant_date.year
            - birth_date.year
            - (
                (relevant_date.month, relevant_date.day)
                < (birth_date.month, birth_date.day)
            )
        )
        if age < configuration.minimum_age or age > MAX_REASONABLE_AGE:
            raise ValidationError(
                "The registration profile does not meet the edition age policy.",
                code="registration_age_policy",
            )
        policy: MinorRegistrationPolicy | None = getattr(
            configuration,
            "minor_policy",
            None,
        )
        requires_guardian_consent = bool(
            policy is not None and policy.enabled and age < policy.minor_age_threshold
        )
        if requires_guardian_consent:
            if not (
                profile_input.guardian_name.strip()
                and profile_input.guardian_email.strip()
                and profile_input.guardian_relationship.strip()
            ):
                raise ValidationError(
                    "A guardian name, email, and relationship are required.",
                    code="guardian_details_required",
                )
            if (
                policy is None
                or profile_input.guardian_notice_version
                != policy.guardian_notice_version
            ):
                raise ValidationError(
                    "Review the current guardian notice before submitting.",
                    code="guardian_notice_changed",
                )

        account_created = account is None
        if account is None:
            if not email or not display_name or not password:
                raise ValidationError(
                    "New public registration requires account details.",
                    code="registration_account_details_required",
                )
            account = Account.objects.create_user(
                email=email,
                password=password,
                display_name=display_name,
            )
            if staff_actor is not None:
                append_audit(
                    _audit_record(
                        actor=staff_actor,
                        capability_code=REGISTER_ON_BEHALF,
                        operation="identity.account.create_for_registration",
                        organization_id=organization_id,
                        edition_id=edition_id,
                        target_type="identity.account",
                        target_id=account.id,
                        correlation_id=correlation_id,
                        outcome=AuditEvent.Outcome.ALLOW,
                        reason_code="staff_assisted_account_creation",
                        obligations=("audit",),
                        changed_fields=("account",),
                        source_channel=source_channel,
                    )
                )

        Participation.objects.get_or_create(
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
            defaults={
                "status": Participation.Status.PENDING,
                "edition_name_snapshot": configuration.edition.name,
                "series_name_snapshot": configuration.edition.series.name,
            },
        )
        registration = submit_registration(
            organization_id=organization_id,
            edition_id=edition_id,
            actor=staff_actor or account,
            subject_account=account if staff_actor is not None else None,
            product_id=product_id,
            answers=answers,
            correlation_id=correlation_id,
            source_channel=source_channel,
            now=submitted_at,
            allow_unverified=(
                staff_actor is not None
                or settings.ALLOW_PROVISIONAL_PUBLIC_REGISTRATION
            ),
            requires_guardian_consent=requires_guardian_consent,
            bypass_sale_windows=bypass_sale_windows,
            staff_reason=staff_reason,
        )
        if len(profile_input.fursuits) > MAX_FURSUITS:
            raise ValidationError(
                f"A profile may include no more than {MAX_FURSUITS} fursuits.",
                code="too_many_fursuits",
            )
        if profile_input.brings_fursuits != bool(profile_input.fursuits):
            raise ValidationError(
                "Fursuit details must match the bring-fursuits choice.",
                code="fursuit_choice_mismatch",
            )
        if profile_input.directory_country_code and not profile_input.directory_visible:
            raise ValidationError(
                "A public country requires attendee-list consent.",
                code="directory_country_without_consent",
            )

        reusable_profile = None
        if profile_input.reuse_profile_photo_id is not None:
            reusable_profile = (
                AttendeeRegistrationProfile.objects.select_for_update()
                .filter(
                    id=profile_input.reuse_profile_photo_id,
                    account=account,
                    organization_id=organization_id,
                    profile_photo_status=MediaReviewStatus.APPROVED,
                )
                .exclude(profile_photo="")
                .first()
            )
            if reusable_profile is None:
                raise ValidationError(
                    "The selected approved profile image is not reusable here.",
                    code="profile_photo_reuse_denied",
                )

        directory_consent_at = submitted_at if profile_input.directory_visible else None
        processed_profile_photo: ProcessedImage | None = None
        profile_photo: ReadableUpload | None = profile_input.profile_photo
        if profile_photo is not None:
            processed_profile_photo = process_image(profile_photo)
            profile_photo = processed_profile_photo.content
        profile_photo_status = (
            MediaReviewStatus.PENDING if profile_photo else MediaReviewStatus.NONE
        )
        profile_photo_reviewer_id = None
        profile_photo_reviewed_at = None
        profile_photo_reused_from_id = None
        if profile_photo is None and reusable_profile is not None:
            profile_photo = reusable_profile.profile_photo
            profile_photo_status = MediaReviewStatus.APPROVED
            profile_photo_reviewer_id = reusable_profile.profile_photo_reviewed_by_id
            profile_photo_reviewed_at = reusable_profile.profile_photo_reviewed_at
            profile_photo_reused_from_id = reusable_profile.id

        profile = AttendeeRegistrationProfile.objects.create(
            registration=registration,
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
            real_name=profile_input.real_name,
            date_of_birth=profile_input.date_of_birth,
            address_line_1=profile_input.address_line_1,
            address_line_2=profile_input.address_line_2,
            locality=profile_input.locality,
            postal_code=profile_input.postal_code,
            region=profile_input.region,
            country_code=profile_input.country_code,
            emergency_contact_name=profile_input.emergency_contact_name,
            emergency_contact_phone=profile_input.emergency_contact_phone,
            phone_number=profile_input.phone_number,
            telegram_handle=profile_input.telegram_handle,
            pronoun_code=profile_input.pronoun_code,
            other_pronouns=profile_input.other_pronouns,
            pronouns=pronoun_display(
                profile_input.pronoun_code,
                profile_input.other_pronouns,
            ),
            bio=profile_input.bio,
            spoken_language_codes=list(profile_input.spoken_language_codes),
            brings_fursuits=profile_input.brings_fursuits,
            profile_photo=profile_photo,
            profile_photo_status=profile_photo_status,
            profile_photo_reviewed_by_id=profile_photo_reviewer_id,
            profile_photo_reviewed_at=profile_photo_reviewed_at,
            profile_photo_reused_from_id=profile_photo_reused_from_id,
            directory_visible=profile_input.directory_visible,
            directory_country_code=profile_input.directory_country_code,
            directory_consent_version=(
                DIRECTORY_CONSENT_VERSION if profile_input.directory_visible else ""
            ),
            directory_consent_at=directory_consent_at,
            collection_notice_version=COLLECTION_NOTICE_VERSION,
        )
        if processed_profile_photo is not None:
            record_media_safety(
                processed=processed_profile_photo,
                organization_id=organization_id,
                edition_id=edition_id,
                account_id=account.id,
                media_kind=MediaSafetyReceipt.MediaKind.PROFILE_PHOTO,
                media_id=profile.id,
                storage_name=profile.profile_photo.name,
            )
        elif reusable_profile is not None:
            copy_media_safety(
                source_kind=MediaSafetyReceipt.MediaKind.PROFILE_PHOTO,
                source_id=reusable_profile.id,
                source_storage_name=reusable_profile.profile_photo.name,
                target_kind=MediaSafetyReceipt.MediaKind.PROFILE_PHOTO,
                target_id=profile.id,
                target_storage_name=profile.profile_photo.name,
                organization_id=organization_id,
                edition_id=edition_id,
                account_id=account.id,
            )
        for position, fursuit_input in enumerate(profile_input.fursuits):
            reusable_fursuit = None
            if fursuit_input.reuse_from_id is not None:
                reusable_fursuit = (
                    AttendeeFursuit.objects.select_for_update()
                    .filter(
                        id=fursuit_input.reuse_from_id,
                        account=account,
                        organization_id=organization_id,
                        photo_status=MediaReviewStatus.APPROVED,
                    )
                    .exclude(photo="")
                    .first()
                )
                if reusable_fursuit is None:
                    raise ValidationError(
                        "A selected approved fursuit image is not reusable here.",
                        code="fursuit_photo_reuse_denied",
                    )
            processed_fursuit_photo: ProcessedImage | None = None
            fursuit_photo: ReadableUpload | None = fursuit_input.photo
            if fursuit_photo is not None:
                processed_fursuit_photo = process_image(fursuit_photo)
                fursuit_photo = processed_fursuit_photo.content
            fursuit_photo_status = (
                MediaReviewStatus.PENDING if fursuit_photo else MediaReviewStatus.NONE
            )
            fursuit_reviewer_id = None
            fursuit_reviewed_at = None
            fursuit_reused_from_id = None
            if fursuit_photo is None and reusable_fursuit is not None:
                fursuit_photo = reusable_fursuit.photo
                fursuit_photo_status = MediaReviewStatus.APPROVED
                fursuit_reviewer_id = reusable_fursuit.photo_reviewed_by_id
                fursuit_reviewed_at = reusable_fursuit.photo_reviewed_at
                fursuit_reused_from_id = reusable_fursuit.id
            fursuit = AttendeeFursuit.objects.create(
                profile=profile,
                registration=registration,
                organization_id=organization_id,
                edition_id=edition_id,
                account=account,
                position=position,
                name=fursuit_input.name,
                species=fursuit_input.species,
                photo=fursuit_photo,
                photo_status=fursuit_photo_status,
                photo_reviewed_by_id=fursuit_reviewer_id,
                photo_reviewed_at=fursuit_reviewed_at,
                photo_reused_from_id=fursuit_reused_from_id,
            )
            if processed_fursuit_photo is not None:
                record_media_safety(
                    processed=processed_fursuit_photo,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    account_id=account.id,
                    media_kind=MediaSafetyReceipt.MediaKind.FURSUIT_PHOTO,
                    media_id=fursuit.id,
                    storage_name=fursuit.photo.name,
                )
            elif reusable_fursuit is not None:
                copy_media_safety(
                    source_kind=MediaSafetyReceipt.MediaKind.FURSUIT_PHOTO,
                    source_id=reusable_fursuit.id,
                    source_storage_name=reusable_fursuit.photo.name,
                    target_kind=MediaSafetyReceipt.MediaKind.FURSUIT_PHOTO,
                    target_id=fursuit.id,
                    target_storage_name=fursuit.photo.name,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    account_id=account.id,
                )
        append_audit(
            _audit_record(
                actor=staff_actor or account,
                capability_code=(
                    REGISTER_ON_BEHALF if staff_actor is not None else REGISTER_SELF
                ),
                operation=(
                    "registration.profile.create_on_behalf"
                    if staff_actor is not None
                    else "registration.profile.create"
                ),
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.attendee_profile",
                target_id=profile.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=(
                    "staff_assisted_registration"
                    if staff_actor is not None
                    else "self_relationship"
                ),
                obligations=("audit",),
                changed_fields=(
                    "address",
                    "contact",
                    "directory_consent",
                    "emergency_contact",
                    "fursuits",
                    "profile_media",
                    "public_bio",
                    "registration_identity",
                    "spoken_languages",
                ),
                source_channel=source_channel,
            )
        )
        if idempotency_key is not None:
            if not request_digest:
                raise ValidationError(
                    "An idempotent command requires a request digest.",
                    code="registration_request_digest_required",
                )
            RegistrationCommandReceipt.objects.create(
                registration=registration,
                organization_id=organization_id,
                edition_id=edition_id,
                account=account,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                result_state=registration.state,
                result_reference=registration.reference,
            )
        guardian_test_token: str | None = None
        if requires_guardian_consent:
            from maru.registration.guardians import (  # noqa: PLC0415
                create_guardian_consent,
            )

            if policy is None:
                raise RuntimeError("Guardian policy disappeared during submission.")
            _, guardian_test_token = create_guardian_consent(
                registration=registration,
                policy=policy,
                guardian_name=profile_input.guardian_name,
                guardian_email=profile_input.guardian_email,
                relationship=profile_input.guardian_relationship,
            )
        return PublicRegistrationResult(
            account=account,
            registration=registration,
            profile=profile,
            account_created=account_created,
            guardian_consent_required=requires_guardian_consent,
            guardian_test_token=guardian_test_token,
        )


def latest_profile_suggestion(
    *,
    account: Account,
    organization_id: UUID,
    target_edition: EventEdition,
) -> AttendeeRegistrationProfile | None:
    """Return a prior profile as a read-only suggestion, never as shared state."""

    return (
        AttendeeRegistrationProfile.objects.filter(
            account=account,
            organization_id=organization_id,
            edition__starts_on__lt=target_edition.starts_on,
        )
        .exclude(edition_id=target_edition.id)
        .select_related("edition", "registration")
        .prefetch_related(
            Prefetch(
                "fursuits",
                queryset=AttendeeFursuit.objects.filter(is_active=True).order_by(
                    "position",
                    "id",
                ),
            )
        )
        .order_by("-edition__starts_on", "-updated_at", "-id")
        .first()
    )


def _reusable_profile_photo(
    *,
    source_id: UUID,
    account: Account,
    organization_id: UUID,
) -> AttendeeRegistrationProfile:
    source = (
        AttendeeRegistrationProfile.objects.select_for_update()
        .filter(
            id=source_id,
            account=account,
            organization_id=organization_id,
            profile_photo_status=MediaReviewStatus.APPROVED,
        )
        .exclude(profile_photo="")
        .first()
    )
    if source is None:
        raise ValidationError(
            "The selected approved profile image is not reusable here.",
            code="profile_photo_reuse_denied",
        )
    return source


def _reusable_fursuit_photo(
    *,
    source_id: UUID,
    account: Account,
    organization_id: UUID,
) -> AttendeeFursuit:
    source = (
        AttendeeFursuit.objects.select_for_update()
        .filter(
            id=source_id,
            account=account,
            organization_id=organization_id,
            photo_status=MediaReviewStatus.APPROVED,
        )
        .exclude(photo="")
        .first()
    )
    if source is None:
        raise ValidationError(
            "The selected approved fursuit image is not reusable here.",
            code="fursuit_photo_reuse_denied",
        )
    return source


def profile_is_editable(
    profile: AttendeeRegistrationProfile,
    *,
    now: datetime | None = None,
) -> bool:
    changed_at = now or timezone.now()
    return (
        profile.account.is_active
        and profile.edition.lifecycle
        not in (EventEdition.Lifecycle.ARCHIVED, EventEdition.Lifecycle.CANCELLED)
        and profile.edition.ends_on >= timezone.localdate(changed_at)
    )


def _apply_profile_photo(
    *,
    profile: AttendeeRegistrationProfile,
    profile_input: AttendeeProfileInput,
    account: Account,
) -> tuple[ProcessedImage | None, AttendeeRegistrationProfile | None]:
    if profile_input.profile_photo is not None:
        processed = process_image(profile_input.profile_photo)
        profile.profile_photo = processed.content
        profile.profile_photo_status = MediaReviewStatus.PENDING
        profile.profile_photo_reviewed_by_id = None
        profile.profile_photo_reviewed_at = None
        profile.profile_photo_review_note = ""
        profile.profile_photo_reused_from_id = None
        return processed, None
    if profile_input.reuse_profile_photo_id is not None:
        source = _reusable_profile_photo(
            source_id=profile_input.reuse_profile_photo_id,
            account=account,
            organization_id=profile.organization_id,
        )
        profile.profile_photo = source.profile_photo
        profile.profile_photo_status = MediaReviewStatus.APPROVED
        profile.profile_photo_reviewed_by_id = source.profile_photo_reviewed_by_id
        profile.profile_photo_reviewed_at = source.profile_photo_reviewed_at
        profile.profile_photo_review_note = source.profile_photo_review_note
        profile.profile_photo_reused_from_id = source.id
        return None, source
    if profile_input.keep_profile_photo:
        return None, None
    profile.profile_photo = ""
    profile.profile_photo_status = MediaReviewStatus.NONE
    profile.profile_photo_reviewed_by_id = None
    profile.profile_photo_reviewed_at = None
    profile.profile_photo_review_note = ""
    profile.profile_photo_reused_from_id = None
    return None, None


def _apply_fursuit_photo(
    *,
    fursuit: AttendeeFursuit,
    fursuit_input: AttendeeFursuitInput,
    account: Account,
) -> tuple[ProcessedImage | None, AttendeeFursuit | None]:
    if fursuit_input.photo is not None:
        processed = process_image(fursuit_input.photo)
        fursuit.photo = processed.content
        fursuit.photo_status = MediaReviewStatus.PENDING
        fursuit.photo_reviewed_by_id = None
        fursuit.photo_reviewed_at = None
        fursuit.photo_review_note = ""
        fursuit.photo_reused_from_id = None
        return processed, None
    if fursuit_input.reuse_from_id is not None:
        source = _reusable_fursuit_photo(
            source_id=fursuit_input.reuse_from_id,
            account=account,
            organization_id=fursuit.organization_id,
        )
        fursuit.photo = source.photo
        fursuit.photo_status = MediaReviewStatus.APPROVED
        fursuit.photo_reviewed_by_id = source.photo_reviewed_by_id
        fursuit.photo_reviewed_at = source.photo_reviewed_at
        fursuit.photo_review_note = source.photo_review_note
        fursuit.photo_reused_from_id = source.id
        return None, source
    if fursuit_input.keep_photo:
        return None, None
    fursuit.photo = ""
    fursuit.photo_status = MediaReviewStatus.NONE
    fursuit.photo_reviewed_by_id = None
    fursuit.photo_reviewed_at = None
    fursuit.photo_review_note = ""
    fursuit.photo_reused_from_id = None
    return None, None


def update_attendee_profile(  # noqa: PLR0912, PLR0915
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    profile_input: AttendeeProfileInput,
    correlation_id: UUID,
    source_channel: str = "public_web",
    now: datetime | None = None,
) -> AttendeeRegistrationProfile:
    """Update only the mutable current-edition profile projection."""

    changed_at = now or timezone.now()
    if not actor.is_active:
        raise ValidationError(
            "Inactive accounts cannot change attendee profiles.",
            code="inactive_account",
        )
    if len(profile_input.fursuits) > MAX_FURSUITS:
        raise ValidationError(
            f"A profile may include no more than {MAX_FURSUITS} fursuits.",
            code="too_many_fursuits",
        )
    if profile_input.brings_fursuits != bool(profile_input.fursuits):
        raise ValidationError(
            "Fursuit details must match the bring-fursuits choice.",
            code="fursuit_choice_mismatch",
        )

    with transaction.atomic():
        profile = (
            AttendeeRegistrationProfile.objects.select_for_update()
            .select_related(
                "account",
                "edition",
                "registration",
                "registration__configuration",
            )
            .get(
                organization_id=organization_id,
                edition_id=edition_id,
                account=actor,
            )
        )
        obligations = _require_decision(
            actor=actor,
            capability_code=MANAGE_SELF_PROFILE,
            target=resolve_owned_target(resource=profile),
            operation="registration.profile.update",
            target_type="registration.attendee_profile",
            target_id=profile.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        if not profile_is_editable(profile, now=changed_at):
            raise ValidationError(
                "This convention profile is historical and can no longer be changed.",
                code="historical_profile",
            )
        relevant_date = profile.edition.starts_on
        age = (
            relevant_date.year
            - profile_input.date_of_birth.year
            - (
                (relevant_date.month, relevant_date.day)
                < (
                    profile_input.date_of_birth.month,
                    profile_input.date_of_birth.day,
                )
            )
        )
        if (
            age < profile.registration.configuration.minimum_age
            or age > MAX_REASONABLE_AGE
        ):
            raise ValidationError(
                "The profile does not meet the edition age policy.",
                code="registration_age_policy",
            )

        profile.real_name = profile_input.real_name
        profile.date_of_birth = profile_input.date_of_birth
        profile.address_line_1 = profile_input.address_line_1
        profile.address_line_2 = profile_input.address_line_2
        profile.locality = profile_input.locality
        profile.postal_code = profile_input.postal_code
        profile.region = profile_input.region
        profile.country_code = profile_input.country_code
        profile.emergency_contact_name = profile_input.emergency_contact_name
        profile.emergency_contact_phone = profile_input.emergency_contact_phone
        profile.phone_number = profile_input.phone_number
        profile.telegram_handle = profile_input.telegram_handle
        profile.pronoun_code = profile_input.pronoun_code
        profile.other_pronouns = profile_input.other_pronouns
        profile.pronouns = pronoun_display(
            profile_input.pronoun_code,
            profile_input.other_pronouns,
        )
        profile.bio = profile_input.bio
        profile.spoken_language_codes = list(profile_input.spoken_language_codes)
        profile.brings_fursuits = profile_input.brings_fursuits
        if profile_input.directory_country_code and not profile_input.directory_visible:
            raise ValidationError(
                "A public country requires attendee-list consent.",
                code="directory_country_without_consent",
            )
        previous_profile_storage = (
            profile.profile_photo.name if profile.profile_photo else ""
        )
        processed_profile, reused_profile = _apply_profile_photo(
            profile=profile,
            profile_input=profile_input,
            account=actor,
        )
        if profile_input.directory_visible:
            if not profile.directory_visible:
                profile.directory_consent_at = changed_at
            profile.directory_consent_version = DIRECTORY_CONSENT_VERSION
        else:
            profile.directory_consent_at = None
            profile.directory_consent_version = ""
        profile.directory_visible = profile_input.directory_visible
        profile.directory_country_code = (
            profile_input.directory_country_code
            if profile_input.directory_visible
            else ""
        )
        profile.aggregate_version += 1
        profile.save()
        if (
            previous_profile_storage
            and previous_profile_storage != profile.profile_photo.name
        ):
            transaction.on_commit(
                partial(
                    dispose_storage_if_unreferenced,
                    previous_profile_storage,
                )
            )
        if processed_profile is not None:
            record_media_safety(
                processed=processed_profile,
                organization_id=organization_id,
                edition_id=edition_id,
                account_id=actor.id,
                media_kind=MediaSafetyReceipt.MediaKind.PROFILE_PHOTO,
                media_id=profile.id,
                storage_name=profile.profile_photo.name,
            )
        elif reused_profile is not None:
            copy_media_safety(
                source_kind=MediaSafetyReceipt.MediaKind.PROFILE_PHOTO,
                source_id=reused_profile.id,
                source_storage_name=reused_profile.profile_photo.name,
                target_kind=MediaSafetyReceipt.MediaKind.PROFILE_PHOTO,
                target_id=profile.id,
                target_storage_name=profile.profile_photo.name,
                organization_id=organization_id,
                edition_id=edition_id,
                account_id=actor.id,
            )

        current_fursuits = {
            fursuit.id: fursuit
            for fursuit in AttendeeFursuit.objects.select_for_update().filter(
                profile=profile
            )
        }
        provided_ids = {
            item.fursuit_id
            for item in profile_input.fursuits
            if item.fursuit_id is not None
        }
        if not provided_ids.issubset(current_fursuits):
            raise ValidationError(
                "A fursuit entry does not belong to this convention profile.",
                code="fursuit_scope_mismatch",
            )
        AttendeeFursuit.objects.filter(profile=profile).update(is_active=False)

        for position, fursuit_input in enumerate(profile_input.fursuits):
            if fursuit_input.fursuit_id is None:
                fursuit = AttendeeFursuit(
                    profile=profile,
                    registration=profile.registration,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    account=actor,
                )
            else:
                fursuit = current_fursuits[fursuit_input.fursuit_id]
            previous_fursuit_storage = fursuit.photo.name if fursuit.photo else ""
            fursuit.position = position
            fursuit.name = fursuit_input.name
            fursuit.species = fursuit_input.species
            fursuit.is_active = True
            processed_fursuit, reused_fursuit = _apply_fursuit_photo(
                fursuit=fursuit,
                fursuit_input=fursuit_input,
                account=actor,
            )
            fursuit.save()
            if (
                previous_fursuit_storage
                and previous_fursuit_storage != fursuit.photo.name
            ):
                transaction.on_commit(
                    partial(
                        dispose_storage_if_unreferenced,
                        previous_fursuit_storage,
                    )
                )
            if processed_fursuit is not None:
                record_media_safety(
                    processed=processed_fursuit,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    account_id=actor.id,
                    media_kind=MediaSafetyReceipt.MediaKind.FURSUIT_PHOTO,
                    media_id=fursuit.id,
                    storage_name=fursuit.photo.name,
                )
            elif reused_fursuit is not None:
                copy_media_safety(
                    source_kind=MediaSafetyReceipt.MediaKind.FURSUIT_PHOTO,
                    source_id=reused_fursuit.id,
                    source_storage_name=reused_fursuit.photo.name,
                    target_kind=MediaSafetyReceipt.MediaKind.FURSUIT_PHOTO,
                    target_id=fursuit.id,
                    target_storage_name=fursuit.photo.name,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    account_id=actor.id,
                )

        registration = profile.registration
        _append_timeline(
            registration=registration,
            kind="profile_updated",
            title="Attendee profile updated",
            summary=(
                "Your current convention profile and public-list preference "
                "were updated. Submitted convention answers were not changed."
            ),
            occurred_at=changed_at,
            actor_kind="account",
            actor_id=actor.id,
            correlation_id=correlation_id,
        )
        audit_event = append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_SELF_PROFILE,
                operation="registration.profile.update",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.attendee_profile",
                target_id=profile.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="self_relationship",
                obligations=obligations,
                changed_fields=(
                    "contact",
                    "directory_consent",
                    "fursuits",
                    "profile_media",
                    "public_bio",
                    "registration_identity",
                    "spoken_languages",
                ),
                source_channel=source_channel,
            )
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="registration.profile.updated.v1",
                schema_version=1,
                organization_id=organization_id,
                event_edition_id=edition_id,
                aggregate_type="registration.attendee_profile",
                aggregate_id=profile.id,
                aggregate_version=profile.aggregate_version,
                payload={
                    "action": "updated",
                    "reference": registration.reference,
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="registration-operational",
            ),
            workload_pool="core",
        )
        return profile


def review_attendee_media(  # noqa: PLR0915
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    media_kind: str,
    media_id: UUID,
    decision: str,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "api",
    now: datetime | None = None,
) -> AttendeeRegistrationProfile | AttendeeFursuit:
    """Approve or reject one exact uploaded profile or fursuit image."""

    if decision not in (
        MediaReviewStatus.APPROVED,
        MediaReviewStatus.REJECTED,
    ):
        raise ValidationError(
            "Media review must approve or reject the image.",
            code="invalid_media_review_decision",
        )
    reason = reason.strip()
    if not reason:
        raise ValidationError(
            "Media review requires a reason.",
            code="media_review_reason_required",
        )
    reviewed_at = now or timezone.now()
    with transaction.atomic():
        if media_kind == "profile_photo":
            profile_item = (
                AttendeeRegistrationProfile.objects.select_for_update()
                .select_related("registration", "account", "edition")
                .get(
                    id=media_id,
                    organization_id=organization_id,
                    edition_id=edition_id,
                )
            )
            item: AttendeeRegistrationProfile | AttendeeFursuit = profile_item
            profile = profile_item
            if not profile.profile_photo:
                raise ValidationError(
                    "There is no profile image to review.",
                    code="media_missing",
                )
            current_status = profile.profile_photo_status
            storage_name = profile.profile_photo.name
            target_type = "registration.attendee_profile"
        elif media_kind == "fursuit_photo":
            item = (
                AttendeeFursuit.objects.select_for_update()
                .select_related("profile", "registration", "account", "edition")
                .get(
                    id=media_id,
                    organization_id=organization_id,
                    edition_id=edition_id,
                )
            )
            profile = item.profile
            if not item.photo:
                raise ValidationError(
                    "There is no fursuit image to review.",
                    code="media_missing",
                )
            current_status = item.photo_status
            storage_name = item.photo.name
            target_type = "registration.attendee_fursuit"
        else:
            raise ValidationError(
                "Unknown attendee media kind.",
                code="unknown_media_kind",
            )
        obligations = _require_decision(
            actor=actor,
            capability_code=MODERATE_PUBLIC_PROFILE,
            target=resolve_edition_target(
                organization_id=organization_id,
                edition_id=edition_id,
            ),
            operation="registration.profile_media.review",
            target_type=target_type,
            target_id=item.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        if decision == MediaReviewStatus.APPROVED and not media_is_safe(
            media_kind=media_kind,
            media_id=item.id,
            storage_name=storage_name,
        ):
            raise ValidationError(
                "The image has no current malware and decoder safety receipt.",
                code="media_safety_receipt_missing",
            )
        if not profile_is_editable(profile, now=reviewed_at):
            raise ValidationError(
                "Historical convention profile images can no longer be reviewed.",
                code="historical_profile",
            )
        if current_status == MediaReviewStatus.NONE:
            raise ValidationError(
                "There is no attendee image to review.",
                code="media_missing",
            )
        if isinstance(item, AttendeeRegistrationProfile):
            item.aggregate_version += 1
            item.profile_photo_status = decision
            item.profile_photo_reviewed_by = actor
            item.profile_photo_reviewed_at = reviewed_at
            item.profile_photo_review_note = reason
            item.save(
                update_fields=(
                    "profile_photo_status",
                    "profile_photo_reviewed_by",
                    "profile_photo_reviewed_at",
                    "profile_photo_review_note",
                    "aggregate_version",
                    "updated_at",
                )
            )
        else:
            item.photo_status = decision
            item.photo_reviewed_by = actor
            item.photo_reviewed_at = reviewed_at
            item.photo_review_note = reason
            item.save(
                update_fields=(
                    "photo_status",
                    "photo_reviewed_by",
                    "photo_reviewed_at",
                    "photo_review_note",
                    "updated_at",
                )
            )
            profile.aggregate_version += 1
            profile.save(update_fields=("aggregate_version", "updated_at"))
        registration = profile.registration
        friendly_kind = (
            "profile image" if media_kind == "profile_photo" else "fursuit image"
        )
        review_outcome = (
            "approved for public use"
            if decision == MediaReviewStatus.APPROVED
            else "not approved"
        )
        _append_timeline(
            registration=registration,
            kind="profile_media_reviewed",
            title=f"{friendly_kind.title()} review completed",
            summary=(f"Your {friendly_kind} was {review_outcome}. Reason: {reason}"),
            occurred_at=reviewed_at,
            actor_kind="account",
            actor_id=actor.id,
            correlation_id=correlation_id,
        )
        audit_event = append_audit(
            _audit_record(
                actor=actor,
                capability_code=MODERATE_PUBLIC_PROFILE,
                operation="registration.profile_media.review",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type=target_type,
                target_id=item.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="media_review_completed",
                obligations=obligations,
                changed_fields=("media_review",),
                source_channel=source_channel,
            )
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="registration.profile.media_reviewed.v1",
                schema_version=1,
                organization_id=organization_id,
                event_edition_id=edition_id,
                aggregate_type="registration.attendee_profile",
                aggregate_id=profile.id,
                aggregate_version=profile.aggregate_version,
                payload={
                    "decision": decision,
                    "media_kind": media_kind,
                    "reference": registration.reference,
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="registration-operational",
            ),
            workload_pool="core",
        )
        return item


def confirm_demo_payment(
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    registration_id: UUID,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "api",
    now: datetime | None = None,
) -> Registration:
    if not actor.is_active:
        raise ValidationError(
            "This account cannot complete a registration payment.",
            code="registration_account_inactive",
        )
    if not settings.DEMO_PAYMENT_ADAPTER_ENABLED:
        raise ValidationError(
            "The simulated payment adapter is disabled.",
            code="demo_payment_disabled",
        )
    owned_registration = Registration.objects.filter(
        id=registration_id,
        organization_id=organization_id,
        edition_id=edition_id,
        account=actor,
    ).first()
    obligations = _require_decision(
        actor=actor,
        capability_code=REGISTER_SELF,
        target=(
            resolve_owned_target(resource=owned_registration)
            if owned_registration is not None
            else None
        ),
        operation="registration.payment.demo_confirm",
        target_type="registration.registration",
        target_id=registration_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    paid_at = now or timezone.now()
    with transaction.atomic():
        existing = PaymentAttempt.objects.filter(
            provider="demo",
            idempotency_key=idempotency_key,
        ).first()
        registration = (
            Registration.objects.select_for_update()
            .select_related("product")
            .get(
                id=registration_id,
                organization_id=organization_id,
                edition_id=edition_id,
                account=actor,
            )
        )
        replacement = (
            AdmissionTierReplacement.objects.select_for_update()
            .filter(
                registration=registration,
                status=AdmissionTierReplacement.Status.PAYMENT_PENDING,
            )
            .first()
        )
        if existing is not None:
            if existing.registration_id != registration.id:
                raise ValidationError(
                    "The payment idempotency key belongs to another operation.",
                    code="payment_idempotency_conflict",
                )
            return registration
        replacement_payment = (
            replacement is not None
            and registration.state
            in {Registration.State.CONFIRMED, Registration.State.CHECKED_IN}
            and registration.product_id == replacement.source_product_id
        )
        if (
            registration.state != Registration.State.PAYMENT_PENDING
            and not replacement_payment
        ):
            raise ValidationError(
                "This registration is not waiting for payment.",
                code="registration_not_payment_pending",
            )
        payment_due_at = (
            replacement.payment_due_at
            if replacement_payment and replacement is not None
            else registration.payment_due_at
        )
        if payment_due_at is not None and paid_at >= payment_due_at:
            raise ValidationError(
                "The payment reservation has expired. Check your registration "
                "for a new offer or contact Registration.",
                code="registration_payment_deadline_passed",
            )
        PaymentAttempt.objects.create(
            registration=registration,
            organization_id=organization_id,
            edition_id=edition_id,
            provider="demo",
            provider_reference=f"demo-{idempotency_key}",
            idempotency_key=idempotency_key,
            amount_minor=(
                replacement.amount_due_minor
                if replacement_payment and replacement is not None
                else registration.price_minor_snapshot
            ),
            currency=(
                replacement.currency
                if replacement_payment and replacement is not None
                else registration.currency_snapshot
            ),
            status=PaymentAttempt.Status.SUCCEEDED,
            occurred_at=paid_at,
            safe_result_code=(
                "demo_tier_replacement_succeeded"
                if replacement_payment
                else "demo_payment_succeeded"
            ),
        )
        if replacement_payment and replacement is not None:
            complete_admission_tier_replacement(
                replacement_id=replacement.id,
                correlation_id=correlation_id,
                completed_at=paid_at,
            )
            return Registration.objects.get(id=registration.id)
        previous_state = registration.state
        registration.state = Registration.State.CONFIRMED
        registration.aggregate_version += 1
        registration.confirmed_at = paid_at
        registration.confirmation_basis = Registration.ConfirmationBasis.PROVIDER
        registration.save(
            update_fields=(
                "state",
                "aggregate_version",
                "confirmed_at",
                "confirmation_basis",
                "updated_at",
            )
        )
        _grant_product_entitlement(registration=registration, granted_at=paid_at)
        _append_timeline(
            registration=registration,
            kind="payment_confirmed",
            title="Payment confirmed",
            summary="The demo provider result was reconciled and admission is active.",
            occurred_at=paid_at,
            actor_kind="provider",
            actor_id=None,
            correlation_id=correlation_id,
        )
        audit_event = append_audit(
            _audit_record(
                actor=actor,
                capability_code=REGISTER_SELF,
                operation="registration.payment.demo_confirm",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.registration",
                target_id=registration.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="demo_payment_reconciled",
                obligations=obligations,
                changed_fields=("state", "payment_attempt", "entitlement", "timeline"),
                source_channel=source_channel,
            )
        )
        payment_event, _ = publish_domain_event(
            DomainEventRecord(
                event_name="registration.payment.reconciled.v1",
                schema_version=1,
                organization_id=organization_id,
                event_edition_id=edition_id,
                aggregate_type="registration.registration",
                aggregate_id=registration.id,
                aggregate_version=registration.aggregate_version,
                payload={
                    "from_state": previous_state,
                    "to_state": registration.state,
                    "reference": registration.reference,
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="registration-financial",
            ),
            workload_pool="payments",
        )
        enqueue_event_delivery(
            event=payment_event,
            destination="notifications",
            workload_pool="notifications",
        )
        return registration


def extend_payment_deadline(
    *,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
    actor: Account,
    new_deadline: datetime,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "api",
    now: datetime | None = None,
) -> Registration:
    """Apply one audited, attendee-visible payment-deadline exception."""

    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_EXCEPTIONS,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.payment_deadline.change",
        target_type="registration.registration",
        target_id=registration_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    normalized_reason = _require_reason(reason)
    changed_at = now or timezone.now()
    if new_deadline <= changed_at:
        raise ValidationError(
            {"new_deadline": "The new payment deadline must be in the future."},
            code="payment_deadline_not_future",
        )
    with transaction.atomic():
        registration = Registration.objects.select_for_update().get(
            id=registration_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if registration.state != Registration.State.PAYMENT_PENDING:
            raise ValidationError(
                "Only a payment-pending registration has an adjustable deadline.",
                code="registration_not_payment_pending",
            )
        previous_deadline = registration.payment_due_at
        registration.payment_due_at = new_deadline
        registration.aggregate_version += 1
        registration.save(
            update_fields=("payment_due_at", "aggregate_version", "updated_at")
        )
        _record_adjustment(
            registration=registration,
            kind=RegistrationAdjustment.Kind.PAYMENT_DEADLINE_CHANGED,
            reason=normalized_reason,
            occurred_at=changed_at,
            actor_kind="account",
            actor_id=actor.id,
            previous_deadline=previous_deadline,
            new_deadline=new_deadline,
        )
        _append_timeline(
            registration=registration,
            kind="payment_deadline_changed",
            title="Payment deadline changed",
            summary=(
                f"Registration staff set a new payment deadline: "
                f"{new_deadline.isoformat()}."
            ),
            occurred_at=changed_at,
            actor_kind="account",
            actor_id=actor.id,
            correlation_id=correlation_id,
        )
        audit_event = append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_EXCEPTIONS,
                operation="registration.payment_deadline.change",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.registration",
                target_id=registration.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="payment_deadline_changed",
                obligations=obligations,
                changed_fields=(
                    "payment_due_at",
                    "adjustment",
                    "timeline",
                ),
                source_channel=source_channel,
            )
        )
        _publish_registration_transition(
            registration=registration,
            event_name="registration.payment.deadline_changed.v1",
            from_state=registration.state,
            correlation_id=correlation_id,
            actor_kind="account",
            actor_id=actor.id,
            causation_id=audit_event.id,
        )
        return registration


def waive_registration_payment(
    *,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "api",
    now: datetime | None = None,
) -> Registration:
    """Confirm a registration through an explicit financial exception."""

    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_EXCEPTIONS,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.payment.waive",
        target_type="registration.registration",
        target_id=registration_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    normalized_reason = _require_reason(reason)
    waived_at = now or timezone.now()
    with transaction.atomic():
        registration = (
            Registration.objects.select_for_update()
            .select_related("product")
            .get(
                id=registration_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        if registration.state != Registration.State.PAYMENT_PENDING:
            raise ValidationError(
                "Only a payment-pending registration can receive a waiver.",
                code="registration_not_payment_pending",
            )
        previous_state = registration.state
        registration.state = Registration.State.CONFIRMED
        registration.confirmed_at = waived_at
        registration.confirmation_basis = Registration.ConfirmationBasis.WAIVER
        registration.aggregate_version += 1
        registration.save(
            update_fields=(
                "state",
                "confirmed_at",
                "confirmation_basis",
                "aggregate_version",
                "updated_at",
            )
        )
        _grant_product_entitlement(registration=registration, granted_at=waived_at)
        _record_adjustment(
            registration=registration,
            kind=RegistrationAdjustment.Kind.PAYMENT_WAIVED,
            reason=normalized_reason,
            occurred_at=waived_at,
            actor_kind="account",
            actor_id=actor.id,
            from_state=previous_state,
            to_state=registration.state,
            amount_minor=registration.price_minor_snapshot,
        )
        _append_timeline(
            registration=registration,
            kind="payment_waived",
            title="Payment requirement waived",
            summary=(
                "Authorized registration staff confirmed the registration without "
                "recording a provider payment."
            ),
            occurred_at=waived_at,
            actor_kind="account",
            actor_id=actor.id,
            correlation_id=correlation_id,
        )
        audit_event = append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_EXCEPTIONS,
                operation="registration.payment.waive",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.registration",
                target_id=registration.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="payment_waived",
                obligations=obligations,
                changed_fields=(
                    "state",
                    "confirmation_basis",
                    "entitlement",
                    "adjustment",
                    "timeline",
                ),
                source_channel=source_channel,
            )
        )
        _publish_registration_transition(
            registration=registration,
            event_name="registration.payment.waived.v1",
            from_state=previous_state,
            correlation_id=correlation_id,
            actor_kind="account",
            actor_id=actor.id,
            causation_id=audit_event.id,
            workload_pool="payments",
        )
        return registration


def _promote_waitlist_for_product(
    *,
    product: AdmissionProduct,
    offered_at: datetime,
    correlation_id: UUID,
) -> Registration | None:
    configuration = product.configuration
    if not configuration.automatic_waitlist_promotion:
        return None
    if offered_at >= configuration.closes_at or (
        product.sales_close_at is not None and offered_at >= product.sales_close_at
    ):
        return None
    occupied = Registration.objects.filter(
        configuration=configuration,
        state__in=OCCUPIED_REGISTRATION_STATES,
    )
    if occupied.count() >= effective_configuration_capacity(configuration) or (
        occupied.filter(product=product).count()
        + pending_target_capacity_holds(product, at=offered_at)
        >= effective_product_capacity(product)
    ):
        return None
    registration = (
        Registration.objects.select_for_update(skip_locked=True)
        .select_related("product", "configuration")
        .filter(
            product=product,
            state=Registration.State.WAITLISTED,
            account__is_active=True,
        )
        .order_by("waitlisted_at", "submitted_at", "id")
        .first()
    )
    if registration is None:
        return None
    previous_state = registration.state
    registration.offered_at = offered_at
    if registration.price_minor_snapshot == 0:
        registration.state = Registration.State.CONFIRMED
        registration.confirmed_at = offered_at
        registration.confirmation_basis = Registration.ConfirmationBasis.FREE
        registration.payment_due_at = None
    else:
        registration.state = Registration.State.PAYMENT_PENDING
        registration.payment_due_at = _payment_deadline(
            configuration=configuration,
            product=product,
            starts_at=offered_at,
        )
    registration.aggregate_version += 1
    registration.save(
        update_fields=(
            "state",
            "offered_at",
            "payment_due_at",
            "confirmed_at",
            "confirmation_basis",
            "aggregate_version",
            "updated_at",
        )
    )
    if registration.state == Registration.State.CONFIRMED:
        _grant_product_entitlement(registration=registration, granted_at=offered_at)
    _record_adjustment(
        registration=registration,
        kind=RegistrationAdjustment.Kind.WAITLIST_PROMOTED,
        reason="Automatic first-in waitlist promotion after capacity was released.",
        occurred_at=offered_at,
        actor_kind="workload",
        actor_id=None,
        from_state=previous_state,
        to_state=registration.state,
        new_deadline=registration.payment_due_at,
    )
    _append_timeline(
        registration=registration,
        kind="waitlist_place_offered",
        title="A registration place is available",
        summary=(
            (
                f"Complete payment by {registration.payment_due_at.isoformat()} "
                "to keep the offered place."
            )
            if registration.payment_due_at is not None
            else "The no-cost registration is now confirmed."
        ),
        occurred_at=offered_at,
        actor_kind="workload",
        actor_id=None,
        correlation_id=correlation_id,
    )
    audit_event = _system_audit(
        registration=registration,
        operation="registration.waitlist.promote",
        reason_code="waitlist_promoted",
        correlation_id=correlation_id,
        changed_fields=(
            "state",
            "offered_at",
            "payment_due_at",
            "adjustment",
            "timeline",
        ),
    )
    _publish_registration_transition(
        registration=registration,
        event_name="registration.waitlist.offered.v1",
        from_state=previous_state,
        correlation_id=correlation_id,
        actor_kind="workload",
        actor_id=None,
        causation_id=audit_event.id,
    )
    return registration


def _lifecycle_transition_for(
    *,
    registration: Registration,
    processed_at: datetime,
) -> _LifecycleTransition | None:
    if not registration.account.is_active:
        return _LifecycleTransition(
            counter="inactive_cancelled",
            target_state=Registration.State.CANCELLED,
            adjustment_kind=RegistrationAdjustment.Kind.REGISTRATION_CANCELLED,
            reason="The inactive account's open registration was cancelled.",
            event_name="registration.cancelled.v1",
            timeline_kind="registration_cancelled",
            timeline_title="Registration cancelled",
            timeline_summary=(
                "This open registration was cancelled because the platform account "
                "is inactive. Registration staff can explain next steps."
            ),
            audit_operation="registration.inactive.cancel",
            audit_reason_code="inactive_account_registration_cancelled",
        )
    if registration.state == Registration.State.WAITLISTED and (
        registration.configuration.closes_at <= processed_at
        or (
            registration.product.sales_close_at is not None
            and registration.product.sales_close_at <= processed_at
        )
    ):
        return _LifecycleTransition(
            counter="closed_waitlist_cancelled",
            target_state=Registration.State.CANCELLED,
            adjustment_kind=RegistrationAdjustment.Kind.REGISTRATION_CANCELLED,
            reason="The applicable registration sales period ended.",
            event_name="registration.cancelled.v1",
            timeline_kind="waitlist_closed",
            timeline_title="Waitlist closed",
            timeline_summary=(
                "No place became available before this offer closed. No payment "
                "was taken."
            ),
            audit_operation="registration.waitlist.close",
            audit_reason_code="waitlist_sales_period_closed",
        )
    if (
        registration.state == Registration.State.PAYMENT_PENDING
        and registration.payment_due_at is not None
        and registration.payment_due_at <= processed_at
    ):
        return _LifecycleTransition(
            counter="expired",
            target_state=Registration.State.EXPIRED,
            adjustment_kind=RegistrationAdjustment.Kind.PAYMENT_EXPIRED,
            reason="The configured payment deadline elapsed.",
            event_name="registration.payment.expired.v1",
            timeline_kind="payment_expired",
            timeline_title="Payment time expired",
            timeline_summary=(
                "The reserved place was released because payment was not confirmed "
                "before the deadline."
            ),
            audit_operation="registration.payment.expire",
            audit_reason_code="payment_deadline_elapsed",
        )
    return None


def _apply_lifecycle_transition(
    *,
    registration: Registration,
    transition: _LifecycleTransition,
    processed_at: datetime,
) -> bool:
    correlation_id = uuid4()
    previous_state = registration.state
    registration.state = transition.target_state
    if transition.target_state == Registration.State.EXPIRED:
        registration.expired_at = processed_at
    else:
        registration.cancelled_at = processed_at
    registration.aggregate_version += 1
    registration.save(
        update_fields=(
            "state",
            "expired_at",
            "cancelled_at",
            "aggregate_version",
            "updated_at",
        )
    )
    _record_adjustment(
        registration=registration,
        kind=transition.adjustment_kind,
        reason=transition.reason,
        occurred_at=processed_at,
        actor_kind="workload",
        actor_id=None,
        from_state=previous_state,
        to_state=registration.state,
        previous_deadline=registration.payment_due_at,
    )
    _append_timeline(
        registration=registration,
        kind=transition.timeline_kind,
        title=transition.timeline_title,
        summary=transition.timeline_summary,
        occurred_at=processed_at,
        actor_kind="workload",
        actor_id=None,
        correlation_id=correlation_id,
    )
    audit_event = _system_audit(
        registration=registration,
        operation=transition.audit_operation,
        reason_code=transition.audit_reason_code,
        correlation_id=correlation_id,
        changed_fields=("state", "adjustment", "timeline"),
    )
    _publish_registration_transition(
        registration=registration,
        event_name=transition.event_name,
        from_state=previous_state,
        correlation_id=correlation_id,
        actor_kind="workload",
        actor_id=None,
        causation_id=audit_event.id,
    )
    return (
        _promote_waitlist_for_product(
            product=registration.product,
            offered_at=processed_at,
            correlation_id=uuid4(),
        )
        is not None
    )


def inspect_registration_lifecycle(
    *,
    edition_id: UUID | None = None,
    now: datetime | None = None,
) -> RegistrationLifecycleCandidates:
    """Count the state changes a lifecycle run would attempt at this instant."""

    processed_at = now or timezone.now()
    base = Registration.objects.filter(
        state__in=(
            Registration.State.WAITLISTED,
            Registration.State.PAYMENT_PENDING,
        )
    )
    if edition_id is not None:
        base = base.filter(edition_id=edition_id)
    active_accounts = base.filter(account__is_active=True)
    return RegistrationLifecycleCandidates(
        inactive_cancelled=base.filter(account__is_active=False).count(),
        closed_waitlist_cancelled=active_accounts.filter(
            Q(
                state=Registration.State.WAITLISTED,
                configuration__closes_at__lte=processed_at,
            )
            | Q(
                state=Registration.State.WAITLISTED,
                product__sales_close_at__lte=processed_at,
            )
        ).count(),
        expired=active_accounts.filter(
            state=Registration.State.PAYMENT_PENDING,
            payment_due_at__lte=processed_at,
        ).count(),
    )


def process_registration_lifecycle(
    *,
    edition_id: UUID | None = None,
    now: datetime | None = None,
) -> RegistrationLifecycleResult:
    """Expire abandoned reservations, remove inactive accounts, and promote FIFO."""

    from maru.registration.commerce import (  # noqa: PLC0415
        expire_admission_tier_replacements,
    )

    processed_at = now or timezone.now()
    tier_replacements_expired = expire_admission_tier_replacements(
        edition_id=edition_id,
        now=processed_at,
    )
    base = Registration.objects.filter(
        state__in=(
            Registration.State.WAITLISTED,
            Registration.State.PAYMENT_PENDING,
        )
    )
    if edition_id is not None:
        base = base.filter(edition_id=edition_id)
    candidate_ids = list(
        base.filter(
            Q(account__is_active=False)
            | Q(
                state=Registration.State.WAITLISTED,
                configuration__closes_at__lte=processed_at,
            )
            | Q(
                state=Registration.State.WAITLISTED,
                product__sales_close_at__lte=processed_at,
            )
            | Q(
                state=Registration.State.PAYMENT_PENDING,
                payment_due_at__lte=processed_at,
            )
        )
        .order_by("submitted_at", "id")
        .values_list("id", flat=True)
    )
    counts = {
        "expired": 0,
        "inactive_cancelled": 0,
        "closed_waitlist_cancelled": 0,
        "promoted": 0,
    }
    for registration_id in candidate_ids:
        with transaction.atomic():
            registration = (
                Registration.objects.select_for_update()
                .select_related("account", "product", "configuration")
                .filter(
                    id=registration_id,
                    state__in=(
                        Registration.State.WAITLISTED,
                        Registration.State.PAYMENT_PENDING,
                    ),
                )
                .first()
            )
            if registration is None:
                continue
            transition = _lifecycle_transition_for(
                registration=registration,
                processed_at=processed_at,
            )
            if transition is None:
                continue
            promoted = _apply_lifecycle_transition(
                registration=registration,
                transition=transition,
                processed_at=processed_at,
            )
            counts[transition.counter] += 1
            counts["promoted"] += int(promoted)
    return RegistrationLifecycleResult(
        expired=counts["expired"],
        inactive_cancelled=counts["inactive_cancelled"],
        closed_waitlist_cancelled=counts["closed_waitlist_cancelled"],
        promoted=counts["promoted"],
        tier_replacements_expired=tier_replacements_expired,
    )


def check_in_registration(
    *,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "api",
    now: datetime | None = None,
) -> Registration:
    obligations = _require_decision(
        actor=actor,
        capability_code=CHECK_IN,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.check_in",
        target_type="registration.registration",
        target_id=registration_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    normalized_reason = _require_reason(reason)
    checked_in_at = now or timezone.now()
    with transaction.atomic():
        registration = (
            Registration.objects.select_for_update()
            .filter(
                id=registration_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .first()
        )
        if registration is None:
            raise Registration.DoesNotExist
        if registration.state == Registration.State.CHECKED_IN:
            return registration
        if registration.state != Registration.State.CONFIRMED:
            raise ValidationError(
                "Only a confirmed registration can be checked in.",
                code="registration_not_confirmed",
            )
        previous_state = registration.state
        registration.state = Registration.State.CHECKED_IN
        registration.aggregate_version += 1
        registration.checked_in_at = checked_in_at
        registration.save(
            update_fields=(
                "state",
                "aggregate_version",
                "checked_in_at",
                "updated_at",
            )
        )
        CheckInRecord.objects.create(
            registration=registration,
            organization_id=organization_id,
            edition_id=edition_id,
            actor_id=actor.id,
            checked_in_at=checked_in_at,
            reason=normalized_reason,
        )
        _append_timeline(
            registration=registration,
            kind="checked_in",
            title="Checked in",
            summary="Front Desk confirmed arrival and issued check-in evidence.",
            occurred_at=checked_in_at,
            actor_kind="account",
            actor_id=actor.id,
            correlation_id=correlation_id,
        )
        audit_event = append_audit(
            _audit_record(
                actor=actor,
                capability_code=CHECK_IN,
                operation="registration.check_in",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.registration",
                target_id=registration.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="registration_checked_in",
                obligations=obligations,
                changed_fields=("state", "checked_in_at", "check_in", "timeline"),
                source_channel=source_channel,
            )
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="registration.checked_in.v1",
                schema_version=1,
                organization_id=organization_id,
                event_edition_id=edition_id,
                aggregate_type="registration.registration",
                aggregate_id=registration.id,
                aggregate_version=registration.aggregate_version,
                payload={
                    "from_state": previous_state,
                    "to_state": registration.state,
                    "reference": registration.reference,
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="registration-operational",
            ),
            workload_pool="core",
        )
        return registration
