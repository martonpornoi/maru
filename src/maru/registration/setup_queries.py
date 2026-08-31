"""Bounded, exact-scope Registration setup-start projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import F, Model, Q, QuerySet
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision, decide, resolve_edition_target
from maru.events.models import EventEdition
from maru.participation.models import ParticipationCapacity
from maru.registration.models import (
    AdmissionProduct,
    ConfigurationStatus,
    MinorRegistrationPolicy,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
    RegistrationProvenanceStatus,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
    RegistrationTemplate,
    RegistrationTemplateCatalogControl,
    TemplateStatus,
)
from maru.registration.setup_commands import (
    MAX_SETUP_PRODUCTS,
    MAX_SETUP_QUESTIONS,
    MAX_SETUP_SECTIONS,
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupDependencyError,
    RegistrationSetupLimitExceededError,
    RegistrationSetupSourceUnavailableError,
    RegistrationSetupStateConflictError,
    _lock_target,
    _locked_prior_configuration_source,
)
from maru.registration.starter_catalog import (
    platform_registration_starters_for_profile,
)
from maru.registration.template_lifecycle import (
    RegistrationTemplateStateConflictError,
    require_published_template_evidence,
)

if TYPE_CHECKING:
    from maru.identity.models import Account

MAX_SETUP_SOURCE_OPTIONS = 100
MAX_SETUP_CONFIGURATIONS = 32
MAX_SETUP_CAPACITY_CODES = 256
MAX_SETUP_PROFILE_FIELDS = 128


class _RegistrationSetupProjectionMovedError(RuntimeError):
    """Internal retry signal; never escapes the public query boundary."""


@dataclass(frozen=True, slots=True)
class RegistrationSetupSourceOption:
    """Describe registration setup source option.

    Attributes
    ----------
    source_kind
        The closed source kind discriminator defined by the domain catalog.
    source_id
        The source identifier within the requested scope.
    name
        The human-readable name to normalize or persist.
    version
        The version number associated with the supplied record or contract.
    content_digest
        The canonical digest used to verify content.
    source_edition_id
        The source edition identifier within the requested scope.
    source_edition_name
        The human-readable source edition name shown to authorized readers.
    """

    source_kind: str
    source_id: UUID
    name: str
    version: int
    content_digest: str
    source_edition_id: UUID | None
    source_edition_name: str


@dataclass(frozen=True, slots=True)
class RegistrationSetupConfigurationProjection:
    """Describe registration setup configuration projection.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
    name
        The human-readable name to normalize or persist.
    version
        The version number associated with the supplied record or contract.
    status
        The closed status value to evaluate or expose.
    origin
        The origin retained in this immutable projection.
    provenance_status
        The closed provenance status discriminator defined by the domain catalog.
    content_digest
        The canonical digest used to verify content.
    review_required
        The review required retained in this immutable projection.
    minimum_age
        The minimum age retained in this immutable projection.
    capacity
        The capacity retained in this immutable projection.
    capacity_ceiling
        The non-negative hard limit or requested amount for capacity ceiling.
    """

    id: UUID
    name: str
    version: int
    status: str
    origin: str
    provenance_status: str
    content_digest: str
    review_required: bool
    minimum_age: int
    capacity: int
    capacity_ceiling: int


@dataclass(frozen=True, slots=True)
class RegistrationSetupSectionProjection:
    """Describe registration setup section projection.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
    key
        The lookup, signing, or idempotency key selected by the contract.
    title
        The human-readable title shown to authorized readers.
    description
        The human-readable description shown to authorized readers.
    position
        The workforce position within the exact edition structure.
    question_count
        The bounded number of question records.
    """

    id: UUID
    key: str
    title: str
    description: str
    position: int
    question_count: int


@dataclass(frozen=True, slots=True)
class RegistrationSetupQuestionProjection:
    """Describe registration setup question projection.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
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
    position
        The workforce position within the exact edition structure.
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
    section_id
        The section identifier within the requested scope.
    """

    id: UUID
    key: str
    label: str
    help_text: str
    field_type: str
    required: bool
    position: int
    options: tuple[str, ...]
    purpose: str
    visibility: str
    classification: str
    condition_question_key: str
    condition_value: str
    section_id: UUID | None


@dataclass(frozen=True, slots=True)
class RegistrationSetupProductProjection:
    """Describe registration setup product projection.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
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
    capacity_ceiling
        The non-negative hard limit or requested amount for capacity ceiling.
    position
        The workforce position within the exact edition structure.
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

    id: UUID
    code: str
    name: str
    description: str
    price_minor: int
    capacity: int
    capacity_ceiling: int
    position: int
    entitlement_code: str
    entitlement_name: str
    sales_open_at: object | None
    sales_close_at: object | None
    required_capacity_codes: tuple[str, ...]
    eligibility_explanation: str
    waitlist_enabled: bool
    payment_window_minutes: int | None
    status: str


@dataclass(frozen=True, slots=True)
class RegistrationSetupMinorPolicyProjection:
    """Describe registration setup minor policy projection.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
    enabled
        The enabled retained in this immutable projection.
    minor_age_threshold
        The minor age threshold retained in this immutable projection.
    guardian_notice_version
        The expected guardian notice version used to reject stale updates.
    jurisdiction_code
        The stable jurisdiction code from the relevant closed catalog.
    review_reference
        The provider or source review reference retained for reconciliation.
    """

    id: UUID
    enabled: bool
    minor_age_threshold: int
    guardian_notice_version: str
    jurisdiction_code: str
    review_reference: str


@dataclass(frozen=True, slots=True)
class RegistrationSetupProfileFieldProjection:
    """Describe registration setup profile field projection.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
    key
        The lookup, signing, or idempotency key selected by the contract.
    version
        The version number associated with the supplied record or contract.
    label
        The human-readable label shown to authorized readers.
    help_text
        The help text retained in this immutable projection.
    field_type
        The closed field type discriminator defined by the domain catalog.
    options
        The configured option codes valid for the source question.
    purpose
        The documented purpose constraining collection and processing.
    classification
        The closed sensitivity classification governing disclosure.
    attendee_visible
        The attendee visible retained in this immutable projection.
    audience_policy
        The closed audience policy governing validation or disclosure.
    audience_department_id
        The audience department identifier within the requested scope.
    audience_department_name
        The human-readable audience department name shown to authorized readers.
    writer_policy
        The closed writer policy governing validation or disclosure.
    required
        The required retained in this immutable projection.
    position
        The workforce position within the exact edition structure.
    source_template_id
        The source template identifier within the requested scope.
    source_prior_edition_id
        The source prior edition identifier within the requested scope.
    review_status
        The closed review status discriminator defined by the domain catalog.
    status
        The closed status value to evaluate or expose.
    """

    id: UUID
    key: str
    version: int
    label: str
    help_text: str
    field_type: str
    options: tuple[str, ...]
    purpose: str
    classification: str
    attendee_visible: bool
    audience_policy: str
    audience_department_id: UUID | None
    audience_department_name: str
    writer_policy: str
    required: bool
    position: int
    source_template_id: UUID | None
    source_prior_edition_id: UUID | None
    review_status: str
    status: str


@dataclass(frozen=True, slots=True)
class RegistrationSetupWorkspace:
    """Describe registration setup workspace.

    Attributes
    ----------
    organization_id
        The organization identifier that owns the requested resource.
    series_id
        The convention-series identifier within the organization scope.
    edition_id
        The event edition identifier that scopes the operation.
    setup_state
        The closed setup state discriminator defined by the domain catalog.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    current_configuration
        The current configuration retained in this immutable projection.
    sections
        The sections retained in this immutable projection.
    questions
        The questions retained in this immutable projection.
    products
        The products retained in this immutable projection.
    minor_policy
        The closed minor policy governing validation or disclosure.
    profile_fields
        The canonical profile fields included in the projection or mutation.
    active_capacity_codes
        The active capacity codes retained in this immutable projection.
    question_count
        The bounded number of question records.
    product_count
        The bounded number of product records.
    minor_policy_configured
        The minor policy configured retained in this immutable projection.
    platform_starters
        The platform starters retained in this immutable projection.
    published_templates
        The published templates retained in this immutable projection.
    prior_configurations
        The prior configurations retained in this immutable projection.
    """

    organization_id: UUID
    series_id: UUID
    edition_id: UUID
    setup_state: str
    aggregate_version: int
    current_configuration: RegistrationSetupConfigurationProjection | None
    sections: tuple[RegistrationSetupSectionProjection, ...]
    questions: tuple[RegistrationSetupQuestionProjection, ...]
    products: tuple[RegistrationSetupProductProjection, ...]
    minor_policy: RegistrationSetupMinorPolicyProjection | None
    profile_fields: tuple[RegistrationSetupProfileFieldProjection, ...]
    active_capacity_codes: tuple[str, ...]
    question_count: int
    product_count: int
    minor_policy_configured: bool
    platform_starters: tuple[RegistrationSetupSourceOption, ...]
    published_templates: tuple[RegistrationSetupSourceOption, ...]
    prior_configurations: tuple[RegistrationSetupSourceOption, ...]


def _decision(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
) -> PolicyDecision:
    if (
        actor.pk is None
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
    )
    if not decision.allowed:
        raise RegistrationSetupAuthorizationDeniedError
    return decision


def _bounded[ItemT: Model](
    queryset: QuerySet[ItemT], *, limit: int
) -> tuple[ItemT, ...]:
    rows = tuple(queryset[: limit + 1])
    if len(rows) > limit:
        raise RegistrationSetupLimitExceededError
    return rows


def _source_allowed(
    *,
    actor: Account,
    organization_id: UUID,
    configuration: RegistrationConfiguration,
) -> bool:
    source_series_id = configuration.edition.series_id
    if not EventEdition.objects.filter(
        pk=configuration.edition_id,
        organization_id=organization_id,
        series_id=source_series_id,
        series__organization_id=organization_id,
    ).exists():
        return False
    source_target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=configuration.edition_id,
    )
    if source_target is None:
        return False
    return decide(
        principal=actor,
        capability_code="registration.manage_configuration",
        resource=source_target,
    ).allowed


def _setup_state(configuration: RegistrationConfiguration | None) -> str:
    if configuration is None:
        return "not_configured"
    if configuration.status == ConfigurationStatus.ACTIVE:
        return "active"
    if configuration.status == ConfigurationStatus.DRAFT:
        return "draft_in_review"
    return "retired"


def _published_template_evidence_is_complete(
    template: RegistrationTemplate,
) -> bool:
    try:
        require_published_template_evidence(template)
    except RegistrationTemplateStateConflictError:
        return False
    return True


def _projection_generation(
    *, organization_id: UUID, edition_id: UUID
) -> tuple[tuple[object, ...] | None, tuple[object, ...] | None]:
    setup = (
        RegistrationSetupControl.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .values_list("id", "aggregate_version", "updated_at")
        .first()
    )
    catalog = (
        RegistrationTemplateCatalogControl.objects.filter(
            organization_id=organization_id,
        )
        .values_list("id", "aggregate_version", "updated_at")
        .first()
    )
    return setup, catalog


@transaction.atomic
def _get_registration_setup_workspace_once(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationSetupWorkspace:
    """Return one complete source-selection projection or fail without partial data.

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
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RegistrationSetupWorkspace
        The RegistrationSetupWorkspace produced by get registration setup
        workspace once.

    Raises
    ------
    RegistrationSetupAuthorizationDeniedError
        If the actor lacks the required scoped capability.
    RegistrationSetupLimitExceededError
        If the operation encounters a registration setup limit exceeded
        condition.
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    _RegistrationSetupProjectionMovedError
        If the operation encounters a registration setup projection moved
        condition.
    """
    if not isinstance(correlation_id, UUID) or (
        request_id is not None and not isinstance(request_id, UUID)
    ):
        raise RegistrationSetupStateConflictError
    route = (
        EventEdition.objects.filter(
            pk=edition_id,
            organization_id=organization_id,
            series_id=series_id,
            series__organization_id=organization_id,
        )
        .values("id", "organization_id", "series_id", "starts_on")
        .first()
    )
    if route is None:
        raise RegistrationSetupAuthorizationDeniedError
    generation_before = _projection_generation(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    decision = _decision(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    control = RegistrationSetupControl.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
    ).first()
    configurations = _bounded(
        RegistrationConfiguration.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("-version", "id"),
        limit=MAX_SETUP_CONFIGURATIONS,
    )
    if control is None and configurations:
        raise RegistrationSetupStateConflictError
    if control is not None and not configurations:
        raise RegistrationSetupStateConflictError
    current = next(
        (
            configuration
            for configuration in configurations
            if configuration.status == ConfigurationStatus.ACTIVE
        ),
        configurations[0] if configurations else None,
    )
    sections = (
        _bounded(
            RegistrationSection.objects.filter(configuration=current).order_by(
                "position", "key", "id"
            ),
            limit=MAX_SETUP_SECTIONS,
        )
        if current is not None
        else ()
    )
    questions = (
        _bounded(
            RegistrationQuestion.objects.filter(configuration=current).order_by(
                "position", "key", "id"
            ),
            limit=MAX_SETUP_QUESTIONS,
        )
        if current is not None
        else ()
    )
    products = (
        _bounded(
            AdmissionProduct.objects.filter(configuration=current).order_by(
                "position", "code", "id"
            ),
            limit=MAX_SETUP_PRODUCTS,
        )
        if current is not None
        else ()
    )
    profile_fields = _bounded(
        RegistrationProfileExtensionField.objects.select_related("audience_department")
        .filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .order_by("position", "key", "-version", "id"),
        limit=MAX_SETUP_PROFILE_FIELDS,
    )
    capacity_codes = tuple(
        ParticipationCapacity.objects.filter(
            participation__organization_id=organization_id,
            participation__edition_id=edition_id,
            status=ParticipationCapacity.Status.ACTIVE,
        )
        .order_by("code")
        .values_list("code", flat=True)
        .distinct()[: MAX_SETUP_CAPACITY_CODES + 1]
    )
    if len(capacity_codes) > MAX_SETUP_CAPACITY_CODES:
        raise RegistrationSetupLimitExceededError
    question_counts_by_section: dict[UUID, int] = {}
    for question in questions:
        if question.section_id is not None:
            question_counts_by_section[question.section_id] = (
                question_counts_by_section.get(question.section_id, 0) + 1
            )
    minor_policy = (
        MinorRegistrationPolicy.objects.filter(configuration=current).first()
        if current is not None
        else None
    )
    minor_policy_configured = minor_policy is not None
    template_candidates = _bounded(
        RegistrationTemplate.objects.filter(
            Q(series_id__isnull=True) | Q(series_id=series_id),
            organization_id=organization_id,
            status=TemplateStatus.PUBLISHED,
            provenance_status=RegistrationProvenanceStatus.COMPLETE,
            created_in_catalog_version__isnull=False,
            last_changed_in_catalog_version__isnull=False,
            content_digest__regex=r"^[0-9a-f]{64}$",
        ).order_by("code", "-version", "id"),
        limit=MAX_SETUP_SOURCE_OPTIONS,
    )
    templates: tuple[RegistrationTemplate, ...] = tuple(
        template
        for template in template_candidates
        if _published_template_evidence_is_complete(template)
    )
    prior_candidates = _bounded(
        RegistrationConfiguration.objects.select_related("edition")
        .filter(
            organization_id=organization_id,
            status=ConfigurationStatus.ACTIVE,
            provenance_status=RegistrationProvenanceStatus.COMPLETE,
            created_in_setup_version__isnull=False,
            last_changed_in_setup_version__isnull=False,
            content_digest__regex=r"^[0-9a-f]{64}$",
            edition__registration_setup_control__provenance_status=(
                RegistrationProvenanceStatus.COMPLETE
            ),
            edition__registration_setup_control__origin=F("origin"),
            edition__starts_on__lt=route["starts_on"],
        )
        .exclude(edition_id=edition_id)
        .order_by("-edition__starts_on", "-version", "id"),
        limit=MAX_SETUP_SOURCE_OPTIONS,
    )
    source_scope = _lock_target(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    permitted_prior = []
    for configuration in prior_candidates:
        if not _source_allowed(
            actor=actor,
            organization_id=organization_id,
            configuration=configuration,
        ):
            continue
        try:
            _locked_prior_configuration_source(source_scope, configuration.id)
        except (
            RegistrationSetupDependencyError,
            RegistrationSetupSourceUnavailableError,
        ):
            continue
        permitted_prior.append(configuration)

    # Repeat the exact target decision immediately before releasing labels.
    decision = _decision(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    permitted_prior = [
        configuration
        for configuration in permitted_prior
        if _source_allowed(
            actor=actor,
            organization_id=organization_id,
            configuration=configuration,
        )
    ]
    generation_after = _projection_generation(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if generation_after != generation_before:
        raise _RegistrationSetupProjectionMovedError
    starters = platform_registration_starters_for_profile(
        profile_code=source_scope.edition.adoption_profile_code,
        profile_version=source_scope.edition.adoption_profile_version,
    )
    if len(starters) > MAX_SETUP_SOURCE_OPTIONS:
        raise RegistrationSetupLimitExceededError
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="registration.manage_configuration",
            operation="registration.setup.read",
            target_type="registration.setup",
            target_id=control.id if control else edition_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(decision.obligations)),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "contract_version": "registration-setup-workspace-v1",
                "target_count": (
                    len(starters)
                    + len(templates)
                    + len(permitted_prior)
                    + len(sections)
                    + len(questions)
                    + len(products)
                    + len(profile_fields)
                    + len(capacity_codes)
                    + int(minor_policy_configured)
                ),
            },
            retention_class="registration-restricted",
        ),
        occurred_at=timezone.now(),
    )
    return RegistrationSetupWorkspace(
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        setup_state=_setup_state(current),
        aggregate_version=int(control.aggregate_version) if control else 0,
        current_configuration=(
            RegistrationSetupConfigurationProjection(
                id=current.id,
                name=current.name,
                version=int(current.version),
                status=current.status,
                origin=current.origin,
                provenance_status=current.provenance_status,
                content_digest=current.content_digest,
                review_required=current.review_required,
                minimum_age=int(current.minimum_age),
                capacity=int(current.capacity),
                capacity_ceiling=int(current.capacity_ceiling or current.capacity),
            )
            if current is not None
            else None
        ),
        sections=tuple(
            RegistrationSetupSectionProjection(
                id=section.id,
                key=section.key,
                title=section.title,
                description=section.description,
                position=int(section.position),
                question_count=question_counts_by_section.get(section.id, 0),
            )
            for section in sections
        ),
        questions=tuple(
            RegistrationSetupQuestionProjection(
                id=question.id,
                key=question.key,
                label=question.label,
                help_text=question.help_text,
                field_type=question.field_type,
                required=question.required,
                position=int(question.position),
                options=tuple(question.options),
                purpose=question.purpose,
                visibility=question.visibility,
                classification=question.classification,
                condition_question_key=question.condition_question_key,
                condition_value=question.condition_value,
                section_id=question.section_id,
            )
            for question in questions
        ),
        products=tuple(
            RegistrationSetupProductProjection(
                id=product.id,
                code=product.code,
                name=product.name,
                description=product.description,
                price_minor=int(product.price_minor),
                capacity=int(product.capacity),
                capacity_ceiling=int(product.capacity_ceiling or product.capacity),
                position=int(product.position),
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
            for product in products
        ),
        minor_policy=(
            RegistrationSetupMinorPolicyProjection(
                id=minor_policy.id,
                enabled=minor_policy.enabled,
                minor_age_threshold=int(minor_policy.minor_age_threshold),
                guardian_notice_version=minor_policy.guardian_notice_version,
                jurisdiction_code=minor_policy.jurisdiction_code,
                review_reference=minor_policy.review_reference,
            )
            if minor_policy is not None
            else None
        ),
        profile_fields=tuple(
            RegistrationSetupProfileFieldProjection(
                id=field.id,
                key=field.key,
                version=int(field.version),
                label=field.label,
                help_text=field.help_text,
                field_type=field.field_type,
                options=tuple(field.options),
                purpose=field.purpose,
                classification=field.classification,
                attendee_visible=field.attendee_visible,
                audience_policy=field.audience_policy,
                audience_department_id=field.audience_department_id,
                audience_department_name=(
                    field.audience_department.name
                    if field.audience_department is not None
                    else ""
                ),
                writer_policy=field.writer_policy,
                required=field.required,
                position=int(field.position),
                source_template_id=field.source_template_id,
                source_prior_edition_id=field.source_prior_edition_id,
                review_status=field.review_status,
                status=field.status,
            )
            for field in profile_fields
        ),
        active_capacity_codes=tuple(capacity_codes),
        question_count=len(questions),
        product_count=len(products),
        minor_policy_configured=minor_policy_configured,
        platform_starters=tuple(
            RegistrationSetupSourceOption(
                source_kind=RegistrationSetupOrigin.PLATFORM_STARTER,
                source_id=starter.source_id,
                name=starter.name,
                version=starter.version,
                content_digest=starter.content_digest,
                source_edition_id=None,
                source_edition_name="",
            )
            for starter in starters
        ),
        published_templates=tuple(
            RegistrationSetupSourceOption(
                source_kind=RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
                source_id=template.id,
                name=template.name,
                version=int(template.version),
                content_digest=template.content_digest,
                source_edition_id=None,
                source_edition_name="",
            )
            for template in templates
        ),
        prior_configurations=tuple(
            RegistrationSetupSourceOption(
                source_kind=RegistrationSetupOrigin.PRIOR_EDITION,
                source_id=configuration.id,
                name=configuration.name,
                version=int(configuration.version),
                content_digest=configuration.content_digest,
                source_edition_id=configuration.edition_id,
                source_edition_name=configuration.edition.name,
            )
            for configuration in permitted_prior
        ),
    )


def get_registration_setup_workspace(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationSetupWorkspace:
    """Return one stable projection, retrying one concurrent aggregate movement.

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
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RegistrationSetupWorkspace
        The resolved RegistrationSetupWorkspace for the requested scope.

    Raises
    ------
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    for attempt in range(2):
        try:
            return _get_registration_setup_workspace_once(
                actor=actor,
                organization_id=organization_id,
                series_id=series_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
            )
        except _RegistrationSetupProjectionMovedError:
            if attempt == 1:
                raise RegistrationSetupStateConflictError from None
    raise RegistrationSetupStateConflictError
