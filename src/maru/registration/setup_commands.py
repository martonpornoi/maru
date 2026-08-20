"""Canonical Page 10 command for starting one edition registration setup."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast
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
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    MinorRegistrationPolicy,
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
from maru.registration.setup_content import (
    canonical_digest,
    configuration_content_digest,
    configuration_source_binding_digest,
    minor_policy_payload,
    product_payload,
    question_payload,
    section_payload,
    target_content_digest,
    template_content_digest,
)
from maru.registration.starter_catalog import (
    StarterProduct,
    StarterSection,
    platform_registration_starter,
)
from maru.registration.template_lifecycle import (
    RegistrationTemplateStateConflictError,
    require_published_template_evidence,
)

MAX_SETUP_SECTIONS = 64
MAX_SETUP_QUESTIONS = 256
MAX_SETUP_PRODUCTS = 128
MAX_SETUP_NAME_LENGTH = 160
MAX_SETUP_REASON_LENGTH = 240
MAX_SETUP_CAPACITY = 1_000_000
MAX_SETUP_MINIMUM_AGE = 120
MIN_PAYMENT_WINDOW_MINUTES = 15
MAX_PAYMENT_WINDOW_MINUTES = 43_200
MAX_SOURCE_CHANNEL_LENGTH = 32
_SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")
_EDITABLE_ORGANIZATION_LIFECYCLES = frozenset(
    {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
)
_EDITABLE_EDITION_LIFECYCLES = frozenset(
    {EventEdition.Lifecycle.DRAFT, EventEdition.Lifecycle.PREPARING}
)
_SOURCE_KINDS = frozenset(
    {
        RegistrationSetupOrigin.BLANK,
        RegistrationSetupOrigin.PLATFORM_STARTER,
        RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
        RegistrationSetupOrigin.PRIOR_EDITION,
    }
)


class RegistrationSetupCommandError(RuntimeError):
    """Signal registration setup command."""

    reason_code = "registration_setup_command_failed"

    def __init__(
        self, message: str = "Registration setup could not be started."
    ) -> None:
        """Initialize the RegistrationSetupCommandError instance.

        Parameters
        ----------
        message : str, default='Registration setup could not be started.'
            The disclosure-safe message associated with the outcome.
        """
        super().__init__(message)


class RegistrationSetupAuthorizationDeniedError(RegistrationSetupCommandError):
    """Signal registration setup authorization denied."""

    reason_code = "registration_setup_authorization_denied"


class RegistrationSetupVersionConflictError(RegistrationSetupCommandError):
    """Signal registration setup version conflict."""

    reason_code = "registration_setup_version_conflict"


class RegistrationSetupRetryConflictError(RegistrationSetupCommandError):
    """Signal registration setup retry conflict."""

    reason_code = "registration_setup_retry_conflict"


class RegistrationSetupLifecycleConflictError(RegistrationSetupCommandError):
    """Signal registration setup lifecycle conflict."""

    reason_code = "registration_setup_lifecycle_conflict"


class RegistrationSetupStateConflictError(RegistrationSetupCommandError):
    """Signal registration setup state conflict."""

    reason_code = "registration_setup_state_conflict"


class RegistrationSetupSourceUnavailableError(RegistrationSetupCommandError):
    """Signal registration setup source unavailable."""

    reason_code = "registration_setup_source_unavailable"


class RegistrationSetupLimitExceededError(RegistrationSetupCommandError):
    """Signal registration setup limit exceeded."""

    reason_code = "registration_setup_limit_exceeded"


class RegistrationSetupDependencyError(RegistrationSetupCommandError):
    """Signal registration setup dependency."""

    reason_code = "registration_setup_dependency_failed"


@dataclass(frozen=True, slots=True)
class RegistrationSetupStartResult:
    """Describe registration setup start result.

    Attributes
    ----------
    setup_id
        The setup identifier within the requested scope.
    configuration_id
        The configuration identifier within the requested scope.
    receipt_id
        The receipt identifier within the requested scope.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    configuration_version
        The expected configuration version used to reject stale updates.
    source_kind
        The closed source kind discriminator defined by the domain catalog.
    content_digest
        The canonical digest used to verify content.
    section_count
        The bounded number of section records.
    question_count
        The bounded number of question records.
    product_count
        The bounded number of product records.
    minor_policy_copied
        The minor policy copied retained in this immutable projection.
    replayed
        The replayed retained in this immutable projection.
    """

    setup_id: UUID
    configuration_id: UUID
    receipt_id: UUID
    aggregate_version: int
    configuration_version: int
    source_kind: str
    content_digest: str
    section_count: int
    question_count: int
    product_count: int
    minor_policy_copied: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class _LockedTarget:
    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    actor: Account
    control: RegistrationSetupControl | None
    decision: PolicyDecision
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class _SourceContent:
    origin: str
    template: RegistrationTemplate | None
    edition: EventEdition | None
    configuration: RegistrationConfiguration | None
    source_version: int | None
    source_digest: str
    sections: tuple[
        RegistrationSection | RegistrationTemplateSection | StarterSection,
        ...,
    ]
    questions: tuple[RegistrationQuestion | RegistrationTemplateQuestion, ...]
    products: tuple[
        AdmissionProduct | RegistrationTemplateProduct | StarterProduct,
        ...,
    ]
    minor_policy: MinorRegistrationPolicy | None


def _field_error(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: ValidationError(message, code=code)})


def _strict_uuid(
    value: UUID | None, *, field: str, required: bool = True
) -> UUID | None:
    if value is None and not required:
        return None
    if not isinstance(value, UUID):
        raise _field_error(
            field, "Enter a valid UUID.", "registration_setup_uuid_invalid"
        )
    return value


def _normalized_text(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise _field_error(field, "Enter text.", "registration_setup_text_invalid")
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if not normalized:
        raise _field_error(
            field, "This value is required.", "registration_setup_text_required"
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


def _validate_source_kind(
    value: str, source_id: UUID | None
) -> tuple[str, UUID | None]:
    if value not in _SOURCE_KINDS:
        raise _field_error(
            "source_kind",
            "Choose blank, platform starter, published template, or prior edition.",
            "registration_setup_source_kind_invalid",
        )
    if value == RegistrationSetupOrigin.BLANK:
        if source_id is not None:
            raise _field_error(
                "source_id",
                "Blank setup does not accept a source.",
                "registration_setup_source_unexpected",
            )
        return value, None
    validated = _strict_uuid(source_id, field="source_id")
    return value, validated


def _validate_expected_version(value: int) -> int:
    if type(value) is not int or value != 0:
        raise _field_error(
            "expected_version",
            "Starting registration setup requires expected version zero.",
            "registration_setup_expected_version_invalid",
        )
    return value


def _validate_source_channel(value: str) -> str:
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


def _validate_datetime(value: datetime | None, *, field: str) -> datetime | None:
    if value is not None and (
        not isinstance(value, datetime) or timezone.is_naive(value)
    ):
        raise _field_error(
            field,
            "Enter an aware date and time.",
            "registration_setup_datetime_invalid",
        )
    return value


def _target_decision(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    at: datetime | None = None,
) -> PolicyDecision:
    if (
        actor.pk is None
        or not EventEdition.objects.filter(
            id=edition_id,
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


def _lock_target(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
) -> _LockedTarget:
    organization = (
        Organization.objects.select_for_update().filter(pk=organization_id).first()
    )
    if organization is None:
        raise RegistrationSetupAuthorizationDeniedError
    series = (
        ConventionSeries.objects.select_for_update()
        .filter(
            pk=series_id,
            organization_id=organization.id,
        )
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
        .filter(
            organization_id=organization.id,
            edition_id=edition.id,
        )
        .first()
    )
    persisted_actor = Account.objects.select_for_update().filter(pk=actor.pk).first()
    if persisted_actor is None:
        raise RegistrationSetupAuthorizationDeniedError
    evaluated_at = timezone.now()
    decision = _target_decision(
        actor=persisted_actor,
        organization_id=organization.id,
        series_id=series.id,
        edition_id=edition.id,
        at=evaluated_at,
    )
    return _LockedTarget(
        organization=organization,
        series=series,
        edition=edition,
        actor=persisted_actor,
        control=control,
        decision=decision,
        evaluated_at=evaluated_at,
    )


def _bounded_rows[RowT: Model](
    queryset: QuerySet[RowT], *, limit: int
) -> tuple[RowT, ...]:
    rows = tuple(queryset[: limit + 1])
    if len(rows) > limit:
        raise RegistrationSetupLimitExceededError
    return rows


def _locked_template_source(scope: _LockedTarget, source_id: UUID) -> _SourceContent:
    template = (
        RegistrationTemplate.objects.select_for_update()
        .filter(
            pk=source_id,
            organization_id=scope.organization.id,
            status=TemplateStatus.PUBLISHED,
        )
        .first()
    )
    if (
        template is None
        or (template.series_id is not None and template.series_id != scope.series.id)
        or template.provenance_status != RegistrationProvenanceStatus.COMPLETE
        or not template.content_digest
        or template.created_in_catalog_version is None
        or template.last_changed_in_catalog_version is None
    ):
        raise RegistrationSetupSourceUnavailableError
    sections = _bounded_rows(
        RegistrationTemplateSection.objects.select_for_update()
        .filter(template=template)
        .order_by("position", "key", "id"),
        limit=MAX_SETUP_SECTIONS,
    )
    questions = _bounded_rows(
        RegistrationTemplateQuestion.objects.select_for_update()
        .filter(template=template)
        .order_by("position", "key", "id"),
        limit=MAX_SETUP_QUESTIONS,
    )
    products = _bounded_rows(
        RegistrationTemplateProduct.objects.select_for_update()
        .filter(template=template)
        .order_by("position", "code", "id"),
        limit=MAX_SETUP_PRODUCTS,
    )
    digest = template_content_digest(
        template=template,
        sections=sections,
        questions=questions,
        products=products,
    )
    if template.content_digest != digest:
        raise RegistrationSetupDependencyError
    try:
        require_published_template_evidence(template)
    except RegistrationTemplateStateConflictError as error:
        raise RegistrationSetupSourceUnavailableError from error
    return _SourceContent(
        origin=RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
        template=template,
        edition=None,
        configuration=None,
        source_version=int(template.version),
        source_digest=digest,
        sections=sections,
        questions=questions,
        products=products,
        minor_policy=None,
    )


def _locked_prior_configuration_source(
    scope: _LockedTarget,
    source_id: UUID,
) -> _SourceContent:
    locator = (
        RegistrationConfiguration.objects.filter(
            pk=source_id,
            organization_id=scope.organization.id,
            status=ConfigurationStatus.ACTIVE,
        )
        .values("edition_id", "edition__series_id")
        .first()
    )
    if locator is None or locator["edition_id"] == scope.edition.id:
        raise RegistrationSetupSourceUnavailableError
    source_series = (
        ConventionSeries.objects.select_for_update()
        .filter(
            pk=locator["edition__series_id"],
            organization_id=scope.organization.id,
        )
        .first()
    )
    source_edition = (
        EventEdition.objects.select_for_update()
        .filter(
            pk=locator["edition_id"],
            organization_id=scope.organization.id,
            series=source_series,
            starts_on__lt=scope.edition.starts_on,
        )
        .first()
    )
    if source_series is None or source_edition is None:
        raise RegistrationSetupSourceUnavailableError
    _target_decision(
        actor=scope.actor,
        organization_id=scope.organization.id,
        series_id=source_series.id,
        edition_id=source_edition.id,
        at=scope.evaluated_at,
    )
    configuration = (
        RegistrationConfiguration.objects.select_for_update()
        .filter(
            pk=source_id,
            organization_id=scope.organization.id,
            edition=source_edition,
            status=ConfigurationStatus.ACTIVE,
        )
        .first()
    )
    if configuration is None:
        raise RegistrationSetupSourceUnavailableError
    if (
        configuration.provenance_status != RegistrationProvenanceStatus.COMPLETE
        or not configuration.content_digest
        or configuration.created_in_setup_version is None
        or configuration.last_changed_in_setup_version is None
    ):
        raise RegistrationSetupSourceUnavailableError
    source_control = (
        RegistrationSetupControl.objects.select_for_update()
        .filter(
            organization=scope.organization,
            edition=source_edition,
            origin=configuration.origin,
            provenance_status=RegistrationProvenanceStatus.COMPLETE,
        )
        .first()
    )
    source_receipt = (
        RegistrationSetupCommandReceipt.objects.select_for_update()
        .filter(
            setup=source_control,
            resulting_version=configuration.created_in_setup_version,
            action=RegistrationSetupCommandReceipt.Action.SETUP_STARTED,
        )
        .first()
        if source_control is not None
        else None
    )
    if source_control is None or source_receipt is None:
        raise RegistrationSetupSourceUnavailableError
    try:
        _require_setup_start_evidence(
            scope=replace(
                scope,
                series=source_series,
                edition=source_edition,
                control=source_control,
            ),
            receipt=source_receipt,
            configuration=configuration,
        )
    except RegistrationSetupStateConflictError as error:
        raise RegistrationSetupSourceUnavailableError from error
    sections = _bounded_rows(
        RegistrationSection.objects.select_for_update()
        .filter(configuration=configuration)
        .order_by("position", "key", "id"),
        limit=MAX_SETUP_SECTIONS,
    )
    questions = _bounded_rows(
        RegistrationQuestion.objects.select_for_update()
        .filter(configuration=configuration)
        .order_by("position", "key", "id"),
        limit=MAX_SETUP_QUESTIONS,
    )
    products = _bounded_rows(
        AdmissionProduct.objects.select_for_update()
        .filter(configuration=configuration)
        .order_by("position", "code", "id"),
        limit=MAX_SETUP_PRODUCTS,
    )
    minor_policy = (
        MinorRegistrationPolicy.objects.select_for_update()
        .filter(configuration=configuration)
        .first()
    )
    digest = configuration_content_digest(
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
        minor_policy=minor_policy,
    )
    if configuration.content_digest != digest:
        raise RegistrationSetupDependencyError
    try:
        _require_active_configuration_lifecycle_evidence(
            scope=replace(
                scope,
                series=source_series,
                edition=source_edition,
                control=source_control,
            ),
            configuration=configuration,
            content_digest=digest,
        )
    except RegistrationSetupStateConflictError as error:
        raise RegistrationSetupSourceUnavailableError from error
    return _SourceContent(
        origin=RegistrationSetupOrigin.PRIOR_EDITION,
        template=None,
        edition=source_edition,
        configuration=configuration,
        source_version=int(configuration.version),
        source_digest=digest,
        sections=sections,
        questions=questions,
        products=products,
        minor_policy=minor_policy,
    )


def _source_content(
    scope: _LockedTarget,
    *,
    source_kind: str,
    source_id: UUID | None,
) -> _SourceContent:
    if source_kind == RegistrationSetupOrigin.BLANK:
        return _SourceContent(
            origin=RegistrationSetupOrigin.BLANK,
            template=None,
            edition=None,
            configuration=None,
            source_version=None,
            source_digest="",
            sections=(),
            questions=(),
            products=(),
            minor_policy=None,
        )
    if source_id is None:
        raise RegistrationSetupSourceUnavailableError
    if source_kind == RegistrationSetupOrigin.PLATFORM_STARTER:
        starter = platform_registration_starter(source_id)
        if starter is None:
            raise RegistrationSetupSourceUnavailableError
        return _SourceContent(
            origin=RegistrationSetupOrigin.PLATFORM_STARTER,
            template=None,
            edition=None,
            configuration=None,
            source_version=starter.version,
            source_digest=starter.content_digest,
            sections=starter.sections,
            questions=cast(
                "tuple[RegistrationQuestion | RegistrationTemplateQuestion, ...]",
                starter.questions,
            ),
            products=starter.products,
            minor_policy=None,
        )
    if source_kind == RegistrationSetupOrigin.PUBLISHED_TEMPLATE:
        return _locked_template_source(scope, source_id)
    return _locked_prior_configuration_source(scope, source_id)


def _resolved_metadata(
    *,
    scope: _LockedTarget,
    source: _SourceContent,
    opens_at: datetime | None,
    closes_at: datetime | None,
    capacity: int | None,
    capacity_ceiling: int | None,
    currency: str | None,
    minimum_age: int | None,
    default_payment_window_minutes: int | None,
    waitlist_enabled: bool | None,
    automatic_waitlist_promotion: bool | None,
) -> tuple[datetime, datetime, int, int, str, int, int, bool, bool]:
    inherited = source.configuration
    resolved_opens = (
        opens_at if opens_at is not None else getattr(inherited, "opens_at", None)
    )
    resolved_closes = (
        closes_at if closes_at is not None else getattr(inherited, "closes_at", None)
    )
    resolved_capacity = (
        capacity if capacity is not None else getattr(inherited, "capacity", None)
    )
    inherited_ceiling = getattr(inherited, "capacity_ceiling", None)
    if inherited_ceiling is None:
        inherited_ceiling = getattr(inherited, "capacity", None)
    resolved_capacity_ceiling = (
        capacity_ceiling
        if capacity_ceiling is not None
        else inherited_ceiling
        if inherited_ceiling is not None
        else resolved_capacity
    )
    resolved_currency = (
        currency if currency is not None else getattr(inherited, "currency", None)
    )
    resolved_minimum_age = (
        minimum_age
        if minimum_age is not None
        else getattr(inherited, "minimum_age", 18)
    )
    resolved_payment_window = (
        default_payment_window_minutes
        if default_payment_window_minutes is not None
        else getattr(inherited, "default_payment_window_minutes", 1_440)
    )
    resolved_waitlist = (
        waitlist_enabled
        if waitlist_enabled is not None
        else getattr(inherited, "waitlist_enabled", True)
    )
    resolved_automatic = (
        automatic_waitlist_promotion
        if automatic_waitlist_promotion is not None
        else getattr(inherited, "automatic_waitlist_promotion", True)
    )
    if resolved_opens is None or resolved_closes is None:
        raise _field_error(
            "opens_at",
            "Opening and closing times are required.",
            "registration_setup_metadata_required",
        )
    _validate_datetime(resolved_opens, field="opens_at")
    _validate_datetime(resolved_closes, field="closes_at")
    if resolved_closes <= resolved_opens:
        raise _field_error(
            "closes_at",
            "Closing time must be after opening time.",
            "registration_setup_period_invalid",
        )
    if (
        type(resolved_capacity) is not int
        or not 1 <= resolved_capacity <= MAX_SETUP_CAPACITY
    ):
        raise _field_error(
            "capacity",
            "Enter a capacity from 1 through 1000000.",
            "registration_setup_capacity_invalid",
        )
    if (
        type(resolved_capacity_ceiling) is not int
        or not resolved_capacity <= resolved_capacity_ceiling <= MAX_SETUP_CAPACITY
    ):
        raise _field_error(
            "capacity_ceiling",
            "Enter a hard ceiling at or above the initial capacity, up to 1000000.",
            "registration_setup_capacity_ceiling_invalid",
        )
    if not isinstance(resolved_currency, str):
        raise _field_error(
            "currency",
            "Choose an edition currency.",
            "registration_setup_currency_invalid",
        )
    normalized_currency = resolved_currency.upper()
    if normalized_currency not in scope.edition.currency_codes:
        raise _field_error(
            "currency",
            "Choose an edition currency.",
            "registration_setup_currency_invalid",
        )
    if (
        type(resolved_minimum_age) is not int
        or not 0 <= resolved_minimum_age <= MAX_SETUP_MINIMUM_AGE
    ):
        raise _field_error(
            "minimum_age",
            "Enter an age from 0 through 120.",
            "registration_setup_minimum_age_invalid",
        )
    if (
        type(resolved_payment_window) is not int
        or not MIN_PAYMENT_WINDOW_MINUTES
        <= resolved_payment_window
        <= MAX_PAYMENT_WINDOW_MINUTES
    ):
        raise _field_error(
            "default_payment_window_minutes",
            "Enter 15 through 43200 minutes.",
            "registration_setup_payment_window_invalid",
        )
    if type(resolved_waitlist) is not bool or type(resolved_automatic) is not bool:
        raise _field_error(
            "waitlist_enabled",
            "Choose a valid wait-list policy.",
            "registration_setup_waitlist_invalid",
        )
    if not resolved_waitlist and resolved_automatic:
        raise _field_error(
            "automatic_waitlist_promotion",
            "Automatic promotion requires wait-listing.",
            "registration_setup_waitlist_invalid",
        )
    return (
        resolved_opens,
        resolved_closes,
        resolved_capacity,
        resolved_capacity_ceiling,
        normalized_currency,
        resolved_minimum_age,
        resolved_payment_window,
        resolved_waitlist,
        resolved_automatic,
    )


def _copied_rows(
    *,
    configuration: RegistrationConfiguration,
    source: _SourceContent,
    setup_version: int,
) -> tuple[
    tuple[RegistrationSection, ...],
    tuple[RegistrationQuestion, ...],
    tuple[AdmissionProduct, ...],
]:
    sections = tuple(
        RegistrationSection(
            configuration=configuration,
            key=item.key,
            title=item.title,
            description=item.description,
            position=item.position,
            created_in_setup_version=setup_version,
            last_changed_in_setup_version=setup_version,
        )
        for item in source.sections
    )
    section_by_source = {
        source_section.id: target_section
        for source_section, target_section in zip(
            source.sections, sections, strict=True
        )
    }
    questions = tuple(
        RegistrationQuestion(
            configuration=configuration,
            section=(
                section_by_source.get(item.section_id)
                if item.section_id is not None
                else None
            ),
            key=item.key,
            label=item.label,
            help_text=item.help_text,
            field_type=item.field_type,
            required=item.required,
            position=item.position,
            options=list(item.options),
            purpose=item.purpose,
            visibility=item.visibility,
            classification=item.classification,
            condition_question_key=item.condition_question_key,
            condition_value=item.condition_value,
            created_in_setup_version=setup_version,
            last_changed_in_setup_version=setup_version,
        )
        for item in source.questions
    )
    products = tuple(
        AdmissionProduct(
            configuration=configuration,
            code=item.code,
            name=item.name,
            description=item.description,
            price_minor=item.price_minor,
            capacity=item.capacity,
            capacity_ceiling=item.capacity_ceiling,
            position=item.position,
            entitlement_code=item.entitlement_code,
            entitlement_name=item.entitlement_name,
            sales_open_at=item.sales_open_at,
            sales_close_at=item.sales_close_at,
            required_capacity_codes=list(item.required_capacity_codes),
            eligibility_explanation=item.eligibility_explanation,
            waitlist_enabled=item.waitlist_enabled,
            payment_window_minutes=item.payment_window_minutes,
            status=getattr(item, "status", AdmissionProduct.Status.AVAILABLE),
            created_in_setup_version=setup_version,
            last_changed_in_setup_version=setup_version,
        )
        for item in source.products
    )
    return sections, questions, products


def _result_from_receipt(
    scope: _LockedTarget,
    receipt: RegistrationSetupCommandReceipt,
    *,
    request_digest: str,
) -> RegistrationSetupStartResult:
    if (
        receipt.action != RegistrationSetupCommandReceipt.Action.SETUP_STARTED
        or receipt.request_digest != request_digest
    ):
        raise RegistrationSetupRetryConflictError
    configuration_target = receipt.targets.filter(
        target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
        change_kind=RegistrationCommandChangeKind.CREATED,
    ).first()
    if configuration_target is None:
        raise RegistrationSetupStateConflictError
    configuration = RegistrationConfiguration.objects.filter(
        pk=configuration_target.target_id,
        organization=scope.organization,
        edition=scope.edition,
    ).first()
    if configuration is None:
        raise RegistrationSetupStateConflictError
    _require_setup_start_evidence(
        scope=scope,
        receipt=receipt,
        configuration=configuration,
    )
    target_kinds = tuple(receipt.targets.values_list("target_kind", flat=True))
    return RegistrationSetupStartResult(
        setup_id=receipt.setup_id,
        configuration_id=configuration.id,
        receipt_id=receipt.id,
        aggregate_version=int(receipt.resulting_version),
        configuration_version=int(configuration.version),
        source_kind=configuration.origin,
        content_digest=configuration.content_digest,
        section_count=target_kinds.count(
            RegistrationSetupCommandTarget.TargetKind.SECTION
        ),
        question_count=target_kinds.count(
            RegistrationSetupCommandTarget.TargetKind.QUESTION
        ),
        product_count=target_kinds.count(
            RegistrationSetupCommandTarget.TargetKind.PRODUCT
        ),
        minor_policy_copied=(
            RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY in target_kinds
        ),
        replayed=True,
    )


def _append_targets(
    *,
    receipt: RegistrationSetupCommandReceipt,
    configuration: RegistrationConfiguration,
    sections: tuple[RegistrationSection, ...],
    questions: tuple[RegistrationQuestion, ...],
    products: tuple[AdmissionProduct, ...],
    minor_policy: MinorRegistrationPolicy | None,
) -> None:
    section_keys = {section.id: section.key for section in sections}
    targets = [
        RegistrationSetupCommandTarget(
            receipt=receipt,
            target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
            target_id=configuration.id,
            change_kind=RegistrationCommandChangeKind.CREATED,
            target_schema_version=configuration.version,
            content_digest=configuration_source_binding_digest(configuration),
        )
    ]
    targets.extend(
        RegistrationSetupCommandTarget(
            receipt=receipt,
            target_kind=RegistrationSetupCommandTarget.TargetKind.SECTION,
            target_id=section.id,
            change_kind=RegistrationCommandChangeKind.CREATED,
            content_digest=target_content_digest(
                kind="section", payload=section_payload(section)
            ),
        )
        for section in sections
    )
    targets.extend(
        RegistrationSetupCommandTarget(
            receipt=receipt,
            target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
            target_id=question.id,
            change_kind=RegistrationCommandChangeKind.CREATED,
            content_digest=target_content_digest(
                kind="question",
                payload=question_payload(
                    question,
                    section_key=(
                        section_keys.get(question.section_id)
                        if question.section_id is not None
                        else None
                    ),
                ),
            ),
        )
        for question in questions
    )
    targets.extend(
        RegistrationSetupCommandTarget(
            receipt=receipt,
            target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
            target_id=product.id,
            change_kind=RegistrationCommandChangeKind.CREATED,
            content_digest=target_content_digest(
                kind="product", payload=product_payload(product, include_status=True)
            ),
        )
        for product in products
    )
    if minor_policy is not None:
        policy_payload = minor_policy_payload(minor_policy)
        if policy_payload is None:
            raise RegistrationSetupStateConflictError
        targets.append(
            RegistrationSetupCommandTarget(
                receipt=receipt,
                target_kind=RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
                target_id=minor_policy.id,
                change_kind=RegistrationCommandChangeKind.CREATED,
                content_digest=target_content_digest(
                    kind="minor_policy", payload=policy_payload
                ),
            )
        )
    RegistrationSetupCommandTarget.objects.bulk_create(targets)


def _require_setup_start_evidence(  # noqa: PLR0912
    *,
    scope: _LockedTarget,
    receipt: RegistrationSetupCommandReceipt,
    configuration: RegistrationConfiguration,
) -> AuditEvent:
    """Prove the exact setup-start graph and immutable source binding.

    Parameters
    ----------
    scope : _LockedTarget
        The exact tenant and resource scope of the operation.
    receipt : RegistrationSetupCommandReceipt
        The immutable command receipt proving the accepted transition.
    configuration : RegistrationConfiguration
        The versioned configuration governing validation and behavior.

    Returns
    -------
    AuditEvent
        The resolved AuditEvent for require setup start evidence.

    Raises
    ------
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    # Local import avoids setup_evidence's intentional command-error dependency
    # becoming a module-import cycle.
    from maru.registration.setup_evidence import (  # noqa: PLC0415
        require_setup_command_evidence_graph,
        target_expectation,
    )

    control = scope.control
    maximum_target_count = (
        1 + MAX_SETUP_SECTIONS + MAX_SETUP_QUESTIONS + MAX_SETUP_PRODUCTS + 1
    )
    targets = tuple(
        receipt.targets.select_for_update().order_by(
            "target_kind",
            "target_id",
            "id",
        )[: maximum_target_count + 1]
    )
    allowed_kinds = {
        RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
        RegistrationSetupCommandTarget.TargetKind.SECTION,
        RegistrationSetupCommandTarget.TargetKind.QUESTION,
        RegistrationSetupCommandTarget.TargetKind.PRODUCT,
        RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
    }
    configuration_targets = tuple(
        target
        for target in targets
        if target.target_kind == RegistrationSetupCommandTarget.TargetKind.CONFIGURATION
        and target.target_id == configuration.id
    )
    if (
        control is None
        or receipt.action != RegistrationSetupCommandReceipt.Action.SETUP_STARTED
        or receipt.resulting_version != configuration.created_in_setup_version
        or receipt.resulting_version != 1
        or control.aggregate_version < receipt.resulting_version
        or configuration.created_by_id != receipt.actor_id
        or not 1 <= len(targets) <= maximum_target_count
        or any(
            target.target_kind not in allowed_kinds
            or target.change_kind != RegistrationCommandChangeKind.CREATED
            for target in targets
        )
        or len(configuration_targets) != 1
        or configuration_targets[0].target_schema_version != configuration.version
        or configuration_targets[0].content_digest
        != configuration_source_binding_digest(configuration)
        or sum(
            target.target_kind == RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY
            for target in targets
        )
        > 1
    ):
        raise RegistrationSetupStateConflictError
    nonconfiguration_targets = tuple(
        target
        for target in targets
        if target.target_kind != RegistrationSetupCommandTarget.TargetKind.CONFIGURATION
    )
    if any(
        target.target_schema_version is not None for target in nonconfiguration_targets
    ):
        raise RegistrationSetupStateConflictError
    later_target_keys = frozenset(
        RegistrationSetupCommandTarget.objects.filter(
            receipt__setup=control,
            receipt__resulting_version__gt=receipt.resulting_version,
            target_kind__in={target.target_kind for target in nonconfiguration_targets},
            target_id__in={target.target_id for target in nonconfiguration_targets},
        )
        .values_list("target_kind", "target_id")
        .distinct()[: len(nonconfiguration_targets) + 1]
    )
    section_rows = tuple(
        RegistrationSection.objects.filter(configuration=configuration).order_by(
            "position", "key", "id"
        )[: MAX_SETUP_SECTIONS + 1]
    )
    question_rows = tuple(
        RegistrationQuestion.objects.filter(configuration=configuration).order_by(
            "position", "key", "id"
        )[: MAX_SETUP_QUESTIONS + 1]
    )
    product_rows = tuple(
        AdmissionProduct.objects.filter(configuration=configuration).order_by(
            "position", "code", "id"
        )[: MAX_SETUP_PRODUCTS + 1]
    )
    if (
        len(section_rows) > MAX_SETUP_SECTIONS
        or len(question_rows) > MAX_SETUP_QUESTIONS
        or len(product_rows) > MAX_SETUP_PRODUCTS
    ):
        raise RegistrationSetupStateConflictError
    sections = {section.id: section for section in section_rows}
    questions = {question.id: question for question in question_rows}
    products = {product.id: product for product in product_rows}
    minor_policy = MinorRegistrationPolicy.objects.filter(
        configuration=configuration
    ).first()
    for target in nonconfiguration_targets:
        if (target.target_kind, target.target_id) in later_target_keys:
            continue
        if target.target_kind == RegistrationSetupCommandTarget.TargetKind.SECTION:
            section = sections.get(target.target_id)
            expected_digest = (
                target_content_digest(kind="section", payload=section_payload(section))
                if section is not None
                else ""
            )
        elif target.target_kind == RegistrationSetupCommandTarget.TargetKind.QUESTION:
            question = questions.get(target.target_id)
            expected_digest = (
                target_content_digest(
                    kind="question",
                    payload=question_payload(
                        question,
                        section_key=(
                            sections[question.section_id].key
                            if question is not None and question.section_id in sections
                            else None
                        ),
                    ),
                )
                if question is not None
                else ""
            )
        elif target.target_kind == RegistrationSetupCommandTarget.TargetKind.PRODUCT:
            product = products.get(target.target_id)
            expected_digest = (
                target_content_digest(
                    kind="product",
                    payload=product_payload(product, include_status=True),
                )
                if product is not None
                else ""
            )
        elif minor_policy is not None and minor_policy.id == target.target_id:
            policy_payload = minor_policy_payload(minor_policy)
            if policy_payload is None:
                raise RegistrationSetupStateConflictError
            expected_digest = target_content_digest(
                kind="minor_policy",
                payload=policy_payload,
            )
        else:
            expected_digest = ""
        if target.content_digest != expected_digest:
            raise RegistrationSetupStateConflictError
    target_kinds = {target.target_kind for target in targets}
    changed_fields = tuple(
        field
        for field, present in (
            ("configuration", True),
            ("provenance", True),
            (
                "sections",
                RegistrationSetupCommandTarget.TargetKind.SECTION in target_kinds,
            ),
            (
                "questions",
                RegistrationSetupCommandTarget.TargetKind.QUESTION in target_kinds,
            ),
            (
                "products",
                RegistrationSetupCommandTarget.TargetKind.PRODUCT in target_kinds,
            ),
            (
                "minor_policy",
                RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY in target_kinds,
            ),
        )
        if present
    )
    audit = require_setup_command_evidence_graph(
        scope=scope,
        receipt=receipt,
        primary_target_id=control.id,
        operation_segment="setup",
        expected_targets=tuple(target_expectation(target) for target in targets),
        expected_changed_fields=changed_fields,
        expected_event_payload={
            "configuration_version": "1",
            "source_kind": configuration.origin,
        },
        expected_audit_operation="registration.setup.started",
        expected_audit_target_type="registration.setup",
        expected_contract_version="registration-setup-start-v1",
        expected_event_name="registration.configuration.draft_created.v1",
    )
    if (
        configuration.origin != RegistrationSetupOrigin.BLANK
        and configuration.source_imported_at != audit.occurred_at
    ):
        raise RegistrationSetupStateConflictError
    return audit


def _require_active_configuration_lifecycle_evidence(
    *,
    scope: _LockedTarget,
    configuration: RegistrationConfiguration,
    content_digest: str,
) -> tuple[AuditEvent, AuditEvent]:
    """Prove immutable review and activation graphs for a prior-edition source.

    Parameters
    ----------
    scope : _LockedTarget
        The exact tenant and resource scope of the operation.
    configuration : RegistrationConfiguration
        The versioned configuration governing validation and behavior.
    content_digest : str
        The canonical digest used to verify content.

    Returns
    -------
    tuple[AuditEvent, AuditEvent]
        The matching require active configuration lifecycle evidence records in
        deterministic order.

    Raises
    ------
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    # Local import keeps the generic evidence module's command-error dependency
    # from becoming an import cycle.
    from maru.registration.setup_evidence import (  # noqa: PLC0415
        SetupCommandTargetExpectation,
        require_setup_command_evidence_graph,
    )

    control = scope.control
    if (
        control is None
        or configuration.status
        not in {ConfigurationStatus.ACTIVE, ConfigurationStatus.RETIRED}
        or configuration.organization_id != scope.organization.id
        or configuration.edition_id != scope.edition.id
        or configuration.review_required
        or configuration.activated_at is None
        or configuration.content_digest != content_digest
    ):
        raise RegistrationSetupStateConflictError
    activation_receipts = tuple(
        RegistrationSetupCommandReceipt.objects.filter(
            setup=control,
            action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_ACTIVATED,
            targets__target_kind=(
                RegistrationSetupCommandTarget.TargetKind.CONFIGURATION
            ),
            targets__target_id=configuration.id,
            targets__change_kind=RegistrationCommandChangeKind.ACTIVATED,
        )
        .distinct()
        .order_by("resulting_version", "id")[:2]
    )
    if len(activation_receipts) != 1:
        raise RegistrationSetupStateConflictError
    activation = activation_receipts[0]
    review_receipts = tuple(
        RegistrationSetupCommandReceipt.objects.filter(
            setup=control,
            action=RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED,
            resulting_version=activation.resulting_version - 1,
            targets__target_kind=(
                RegistrationSetupCommandTarget.TargetKind.CONFIGURATION
            ),
            targets__target_id=configuration.id,
            targets__change_kind=RegistrationCommandChangeKind.REVIEWED,
        ).distinct()[:2]
    )
    if (
        len(review_receipts) != 1
        or activation.resulting_version <= 1
        or activation.resulting_version > control.aggregate_version
        or (
            configuration.status == ConfigurationStatus.ACTIVE
            and activation.resulting_version
            != configuration.last_changed_in_setup_version
        )
    ):
        raise RegistrationSetupStateConflictError
    review = review_receipts[0]
    review_audit = require_setup_command_evidence_graph(
        scope=scope,
        receipt=review,
        primary_target_id=configuration.id,
        operation_segment="configuration",
        expected_targets=(
            SetupCommandTargetExpectation(
                target_kind=(RegistrationSetupCommandTarget.TargetKind.CONFIGURATION),
                target_id=configuration.id,
                change_kind=RegistrationCommandChangeKind.REVIEWED,
                target_schema_version=configuration.version,
                content_digest=content_digest,
            ),
        ),
        expected_changed_fields=("review_state",),
        expected_event_payload={
            "action": RegistrationSetupCommandReceipt.Action.CONFIGURATION_REVIEWED,
            "configuration_version": str(configuration.version),
        },
        expected_audit_operation=("registration.setup.configuration_reviewed"),
        expected_audit_target_type="registration.configuration",
        expected_contract_version="registration-configuration-lifecycle-v1",
        expected_event_name="registration.configuration.draft_changed.v1",
    )
    activation_audit = require_setup_command_evidence_graph(
        scope=scope,
        receipt=activation,
        primary_target_id=configuration.id,
        operation_segment="configuration",
        expected_targets=(
            SetupCommandTargetExpectation(
                target_kind=(RegistrationSetupCommandTarget.TargetKind.CONFIGURATION),
                target_id=configuration.id,
                change_kind=RegistrationCommandChangeKind.ACTIVATED,
                target_schema_version=configuration.version,
                content_digest=content_digest,
            ),
        ),
        expected_changed_fields=("status", "activated_at"),
        expected_event_payload={
            "configuration_version": str(configuration.version),
            "source_kind": configuration.origin,
        },
        expected_occurred_at=configuration.activated_at,
        expected_audit_operation=("registration.setup.configuration_activated"),
        expected_audit_target_type="registration.configuration",
        expected_contract_version="registration-configuration-lifecycle-v1",
        expected_event_name="registration.configuration.activated.v1",
    )
    if review_audit.occurred_at > activation_audit.occurred_at:
        raise RegistrationSetupStateConflictError
    return review_audit, activation_audit


def start_registration_setup(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    source_kind: str,
    source_id: UUID | None,
    name: str,
    opens_at: datetime | None,
    closes_at: datetime | None,
    capacity: int | None,
    currency: str | None,
    minimum_age: int | None,
    default_payment_window_minutes: int | None,
    waitlist_enabled: bool | None,
    automatic_waitlist_promotion: bool | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
    capacity_ceiling: int | None = None,
) -> RegistrationSetupStartResult:
    """Start exactly one setup aggregate through copy-on-write.

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
    source_kind : str
        The closed source kind discriminator defined by the domain catalog.
    source_id : UUID | None
        The source identifier within the requested scope.
    name : str
        The human-readable name to normalize or persist.
    opens_at : datetime | None
        The timezone-aware timestamp for opens.
    closes_at : datetime | None
        The timezone-aware timestamp for closes.
    capacity : int | None
        The capacity applied within the audited domain transition.
    currency : str | None
        The supported ISO 4217 currency code for monetary values.
    minimum_age : int | None
        The minimum age applied within the audited domain transition.
    default_payment_window_minutes : int | None
        The default payment window minutes applied within the audited domain transition.
    waitlist_enabled : bool | None
        The waitlist enabled applied within the audited domain transition.
    automatic_waitlist_promotion : bool | None
        The automatic waitlist promotion applied within the audited domain transition.
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
    capacity_ceiling : int | None, default=None
        The non-negative hard limit or requested amount for capacity ceiling.

    Returns
    -------
    RegistrationSetupStartResult
        The resolved RegistrationSetupStartResult for start registration setup.

    Raises
    ------
    RegistrationSetupLifecycleConflictError
        If the operation encounters a registration setup lifecycle conflict
        condition.
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    RegistrationSetupVersionConflictError
        If the supplied aggregate version is stale.
    """
    _strict_uuid(organization_id, field="organization_id")
    _strict_uuid(series_id, field="series_id")
    _strict_uuid(edition_id, field="edition_id")
    _target_decision(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    retry_key = _strict_uuid(retry_key, field="retry_key")  # type: ignore[assignment]
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")  # type: ignore[assignment]
    if request_id is not None:
        _strict_uuid(request_id, field="request_id")
    source_kind, source_id = _validate_source_kind(source_kind, source_id)
    expected_version = _validate_expected_version(expected_version)
    normalized_name = _normalized_text(
        name, field="name", maximum=MAX_SETUP_NAME_LENGTH
    )
    normalized_reason = _normalized_text(
        reason, field="reason", maximum=MAX_SETUP_REASON_LENGTH
    )
    source_channel = _validate_source_channel(source_channel)
    _validate_datetime(opens_at, field="opens_at")
    _validate_datetime(closes_at, field="closes_at")
    request_digest = canonical_digest(
        {
            "action": RegistrationSetupCommandReceipt.Action.SETUP_STARTED,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "source_kind": source_kind,
            "source_id": str(source_id) if source_id else None,
            "name": normalized_name,
            "opens_at": opens_at,
            "closes_at": closes_at,
            "capacity": capacity,
            "capacity_ceiling": capacity_ceiling,
            "currency": currency.upper() if isinstance(currency, str) else currency,
            "minimum_age": minimum_age,
            "default_payment_window_minutes": default_payment_window_minutes,
            "waitlist_enabled": waitlist_enabled,
            "automatic_waitlist_promotion": automatic_waitlist_promotion,
            "expected_version": expected_version,
            "reason": normalized_reason,
        }
    )

    with transaction.atomic():
        scope = _lock_target(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        existing_receipt = RegistrationSetupCommandReceipt.objects.filter(
            organization=scope.organization,
            edition=scope.edition,
            actor=scope.actor,
            retry_key=retry_key,
        ).first()
        if existing_receipt is not None:
            return _result_from_receipt(
                scope,
                existing_receipt,
                request_digest=request_digest,
            )
        if scope.control is not None:
            raise RegistrationSetupVersionConflictError
        if (
            RegistrationConfiguration.objects.select_for_update()
            .filter(edition=scope.edition)
            .exists()
            or RegistrationSetupCommandReceipt.objects.select_for_update()
            .filter(edition=scope.edition)
            .exists()
            or scope.edition.registration_profile_extension_fields.select_for_update()
            .all()
            .exists()
        ):
            raise RegistrationSetupStateConflictError
        if (
            scope.organization.lifecycle not in _EDITABLE_ORGANIZATION_LIFECYCLES
            or scope.edition.lifecycle not in _EDITABLE_EDITION_LIFECYCLES
        ):
            raise RegistrationSetupLifecycleConflictError
        source = _source_content(scope, source_kind=source_kind, source_id=source_id)
        (
            resolved_opens,
            resolved_closes,
            resolved_capacity,
            resolved_capacity_ceiling,
            resolved_currency,
            resolved_minimum_age,
            resolved_payment_window,
            resolved_waitlist,
            resolved_automatic,
        ) = _resolved_metadata(
            scope=scope,
            source=source,
            opens_at=opens_at,
            closes_at=closes_at,
            capacity=capacity,
            capacity_ceiling=capacity_ceiling,
            currency=currency,
            minimum_age=minimum_age,
            default_payment_window_minutes=default_payment_window_minutes,
            waitlist_enabled=waitlist_enabled,
            automatic_waitlist_promotion=automatic_waitlist_promotion,
        )
        setup_version = 1
        configuration = RegistrationConfiguration(
            organization=scope.organization,
            edition=scope.edition,
            name=normalized_name,
            version=1,
            status=ConfigurationStatus.DRAFT,
            source_template=source.template,
            source_edition=source.edition,
            source_configuration=source.configuration,
            origin=source.origin,
            provenance_status=RegistrationProvenanceStatus.COMPLETE,
            source_version=source.source_version,
            source_content_digest=source.source_digest,
            source_imported_at=(
                scope.evaluated_at
                if source.origin != RegistrationSetupOrigin.BLANK
                else None
            ),
            source_imported_by=(
                scope.actor if source.origin != RegistrationSetupOrigin.BLANK else None
            ),
            created_in_setup_version=setup_version,
            last_changed_in_setup_version=setup_version,
            review_required=True,
            review_note="",
            opens_at=resolved_opens,
            closes_at=resolved_closes,
            capacity=resolved_capacity,
            capacity_ceiling=resolved_capacity_ceiling,
            currency=resolved_currency,
            minimum_age=resolved_minimum_age,
            default_payment_window_minutes=resolved_payment_window,
            waitlist_enabled=resolved_waitlist,
            automatic_waitlist_promotion=resolved_automatic,
            created_by_id=scope.actor.id,
        )
        copied_sections, copied_questions, copied_products = _copied_rows(
            configuration=configuration,
            source=source,
            setup_version=setup_version,
        )
        configuration.content_digest = configuration_content_digest(
            name=configuration.name,
            schema_version=configuration.version,
            opens_at=configuration.opens_at,
            closes_at=configuration.closes_at,
            capacity=configuration.capacity,
            capacity_ceiling=configuration.capacity_ceiling,
            currency=configuration.currency,
            minimum_age=configuration.minimum_age,
            default_payment_window_minutes=configuration.default_payment_window_minutes,
            waitlist_enabled=configuration.waitlist_enabled,
            automatic_waitlist_promotion=configuration.automatic_waitlist_promotion,
            sections=copied_sections,
            questions=copied_questions,
            products=copied_products,
            minor_policy=source.minor_policy,
        )
        configuration.save()
        for section in copied_sections:
            section.full_clean(validate_unique=False, validate_constraints=False)
        RegistrationSection.objects.bulk_create(copied_sections)
        for question in copied_questions:
            question.full_clean(validate_unique=False, validate_constraints=False)
        RegistrationQuestion.objects.bulk_create(copied_questions)
        for product in copied_products:
            product.full_clean(validate_unique=False, validate_constraints=False)
        AdmissionProduct.objects.bulk_create(copied_products)
        copied_policy = None
        if source.minor_policy is not None:
            copied_policy = MinorRegistrationPolicy.objects.create(
                configuration=configuration,
                enabled=source.minor_policy.enabled,
                minor_age_threshold=source.minor_policy.minor_age_threshold,
                guardian_notice_version=source.minor_policy.guardian_notice_version,
                jurisdiction_code=source.minor_policy.jurisdiction_code,
                review_reference=source.minor_policy.review_reference,
                reviewed_by=source.minor_policy.reviewed_by,
                reviewed_at=source.minor_policy.reviewed_at,
                created_in_setup_version=setup_version,
                last_changed_in_setup_version=setup_version,
            )
        control = RegistrationSetupControl.objects.create(
            organization=scope.organization,
            edition=scope.edition,
            origin=source.origin,
            provenance_status=RegistrationProvenanceStatus.COMPLETE,
            aggregate_version=setup_version,
        )
        receipt = RegistrationSetupCommandReceipt.objects.create(
            setup=control,
            organization=scope.organization,
            edition=scope.edition,
            action=RegistrationSetupCommandReceipt.Action.SETUP_STARTED,
            resulting_version=setup_version,
            actor=scope.actor,
            reason=normalized_reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
            retry_key=retry_key,
            request_digest=request_digest,
        )
        _append_targets(
            receipt=receipt,
            configuration=configuration,
            sections=copied_sections,
            questions=copied_questions,
            products=copied_products,
            minor_policy=copied_policy,
        )
        changed_fields = tuple(
            field
            for field, present in (
                ("configuration", True),
                ("provenance", True),
                ("sections", bool(copied_sections)),
                ("questions", bool(copied_questions)),
                ("products", bool(copied_products)),
                ("minor_policy", copied_policy is not None),
            )
            if present
        )
        audit_event = append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=scope.actor.id,
                principal_context_id=None,
                organization_id=scope.organization.id,
                event_edition_id=scope.edition.id,
                capability_code="registration.manage_configuration",
                operation="registration.setup.started",
                target_type="registration.setup",
                target_id=control.id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=scope.decision.reason_code,
                correlation_id=correlation_id,
                request_id=request_id or correlation_id,
                source_channel=source_channel,
                obligations=tuple(sorted(scope.decision.obligations)),
                changed_fields=changed_fields,
                idempotency_key_hash=canonical_digest({"retry_key": str(retry_key)}),
                safe_metadata={
                    "policy_version": POLICY_VERSION,
                    "contract_version": "registration-setup-start-v1",
                    "target_count": (
                        1
                        + len(copied_sections)
                        + len(copied_questions)
                        + len(copied_products)
                        + int(copied_policy is not None)
                    ),
                },
                retention_class="registration-restricted",
            ),
            occurred_at=scope.evaluated_at,
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="registration.configuration.draft_created.v1",
                schema_version=1,
                organization_id=scope.organization.id,
                event_edition_id=scope.edition.id,
                aggregate_type="registration.setup",
                aggregate_id=control.id,
                aggregate_version=setup_version,
                payload={
                    "configuration_version": "1",
                    "source_kind": source.origin,
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=scope.actor.id,
                retention_class="registration-restricted",
            ),
            occurred_at=scope.evaluated_at,
        )
        _require_setup_start_evidence(
            scope=replace(scope, control=control),
            receipt=receipt,
            configuration=configuration,
        )
        return RegistrationSetupStartResult(
            setup_id=control.id,
            configuration_id=configuration.id,
            receipt_id=receipt.id,
            aggregate_version=setup_version,
            configuration_version=configuration.version,
            source_kind=source.origin,
            content_digest=configuration.content_digest,
            section_count=len(copied_sections),
            question_count=len(copied_questions),
            product_count=len(copied_products),
            minor_policy_copied=copied_policy is not None,
            replayed=False,
        )
