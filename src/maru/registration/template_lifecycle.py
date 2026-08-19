"""Governed reusable registration-template publication and evidence proofs."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Model, QuerySet
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision, decide, resolve_edition_target
from maru.effects.models import DomainEvent
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from maru.registration.models import (
    RegistrationCommandChangeKind,
    RegistrationProvenanceStatus,
    RegistrationTemplate,
    RegistrationTemplateCatalogCommandReceipt,
    RegistrationTemplateCatalogCommandTarget,
    RegistrationTemplateCatalogControl,
    RegistrationTemplateProduct,
    RegistrationTemplateQuestion,
    RegistrationTemplateSection,
    TemplateStatus,
)
from maru.registration.question_conditions import condition_value_is_compatible
from maru.registration.setup_content import canonical_digest, template_content_digest

MAX_TEMPLATE_SECTIONS = 64
MAX_TEMPLATE_QUESTIONS = 256
MAX_TEMPLATE_PRODUCTS = 128
MAX_TEMPLATE_REASON_LENGTH = 240
MAX_TEMPLATE_SOURCE_CHANNEL_LENGTH = 32
MAX_TEMPLATE_QUESTION_HELP_LENGTH = 2_000
MAX_TEMPLATE_PRODUCT_DESCRIPTION_LENGTH = 2_000
_SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_POLICY_VERSION_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.[1-9][0-9]*\Z")
_EDITABLE_ORGANIZATION_LIFECYCLES = frozenset(
    {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
)
_EDITABLE_EDITION_LIFECYCLES = frozenset(
    {EventEdition.Lifecycle.DRAFT, EventEdition.Lifecycle.PREPARING}
)


class RegistrationTemplateLifecycleError(RuntimeError):
    """Signal registration template lifecycle."""

    reason_code = "registration_template_lifecycle_failed"


class RegistrationTemplateAuthorizationDeniedError(RegistrationTemplateLifecycleError):
    """Signal registration template authorization denied."""

    reason_code = "registration_template_authorization_denied"


class RegistrationTemplateVersionConflictError(RegistrationTemplateLifecycleError):
    """Signal registration template version conflict."""

    reason_code = "registration_template_version_conflict"


class RegistrationTemplateRetryConflictError(RegistrationTemplateLifecycleError):
    """Signal registration template retry conflict."""

    reason_code = "registration_template_retry_conflict"


class RegistrationTemplateStateConflictError(RegistrationTemplateLifecycleError):
    """Signal registration template state conflict."""

    reason_code = "registration_template_state_conflict"


class RegistrationTemplateValidationError(RegistrationTemplateLifecycleError):
    """Signal registration template validation."""

    reason_code = "registration_template_validation_failed"


@dataclass(frozen=True, slots=True)
class RegistrationTemplatePublishResult:
    """Describe registration template publish result.

    Attributes
    ----------
    catalog_id
        The catalog identifier within the requested scope.
    template_id
        The template identifier within the requested scope.
    receipt_id
        The receipt identifier within the requested scope.
    resulting_version
        The expected resulting version used to reject stale updates.
    template_version
        The expected template version used to reject stale updates.
    content_digest
        The canonical digest used to verify content.
    replayed
        The replayed retained in this immutable projection.
    """

    catalog_id: UUID
    template_id: UUID
    receipt_id: UUID
    resulting_version: int
    template_version: int
    content_digest: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class _LockedTemplateScope:
    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    actor: Account
    template: RegistrationTemplate
    catalog: RegistrationTemplateCatalogControl | None
    decision: PolicyDecision


def _field_error(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: ValidationError(message, code=code)})


def _strict_uuid(value: object, *, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise _field_error(
            field, "Enter a valid UUID.", "registration_template_uuid_invalid"
        )
    return value


def _expected_version(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _field_error(
            "expected_version",
            "Enter the current non-negative catalog version.",
            "registration_template_expected_version_invalid",
        )
    return value


def _normalized_reason(value: object) -> str:
    if not isinstance(value, str):
        raise _field_error(
            "reason", "Enter text.", "registration_template_reason_invalid"
        )
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if not normalized:
        raise _field_error(
            "reason", "This value is required.", "registration_template_reason_required"
        )
    if len(normalized) > MAX_TEMPLATE_REASON_LENGTH or any(
        unicodedata.category(character).startswith("C") for character in normalized
    ):
        raise _field_error(
            "reason",
            f"Use at most {MAX_TEMPLATE_REASON_LENGTH} safe characters.",
            "registration_template_reason_invalid",
        )
    return normalized


def _source_channel(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_TEMPLATE_SOURCE_CHANNEL_LENGTH
        or _SOURCE_CHANNEL_PATTERN.fullmatch(value) is None
    ):
        raise _field_error(
            "source_channel",
            "Use a registered source channel.",
            "registration_template_source_channel_invalid",
        )
    return value


def _authorize(
    *, actor: Account, organization_id: UUID, series_id: UUID, edition_id: UUID
) -> PolicyDecision:
    if actor.pk is None:
        raise RegistrationTemplateAuthorizationDeniedError
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if target is None:
        raise RegistrationTemplateAuthorizationDeniedError
    decision = decide(
        principal=actor,
        capability_code="registration.manage_configuration",
        resource=target,
    )
    if (
        not decision.allowed
        or not EventEdition.objects.filter(
            pk=edition_id,
            organization_id=organization_id,
            series_id=series_id,
            series__organization_id=organization_id,
        ).exists()
    ):
        raise RegistrationTemplateAuthorizationDeniedError
    return decision


def _lock_scope(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    template_id: UUID,
) -> _LockedTemplateScope:
    organization = (
        Organization.objects.select_for_update().filter(pk=organization_id).first()
    )
    series = (
        ConventionSeries.objects.select_for_update()
        .filter(pk=series_id, organization_id=organization_id)
        .first()
    )
    edition = (
        EventEdition.objects.select_for_update()
        .filter(
            pk=edition_id,
            organization_id=organization_id,
            series_id=series_id,
        )
        .first()
    )
    persisted_actor = Account.objects.select_for_update().filter(pk=actor.pk).first()
    template = (
        RegistrationTemplate.objects.select_for_update()
        .filter(pk=template_id, organization_id=organization_id)
        .first()
    )
    if (
        organization is None
        or series is None
        or edition is None
        or persisted_actor is None
        or template is None
    ):
        raise RegistrationTemplateAuthorizationDeniedError
    decision = _authorize(
        actor=persisted_actor,
        organization_id=organization.id,
        series_id=series.id,
        edition_id=edition.id,
    )
    if template.series_id is None:
        if not persisted_actor.is_platform_administrator:
            raise RegistrationTemplateAuthorizationDeniedError
    elif template.series_id != series.id:
        raise RegistrationTemplateAuthorizationDeniedError
    catalog = (
        RegistrationTemplateCatalogControl.objects.select_for_update()
        .filter(organization=organization)
        .first()
    )
    return _LockedTemplateScope(
        organization=organization,
        series=series,
        edition=edition,
        actor=persisted_actor,
        template=template,
        catalog=catalog,
        decision=decision,
    )


def _bounded[ItemT: Model](
    queryset: QuerySet[ItemT], *, limit: int
) -> tuple[ItemT, ...]:
    rows = tuple(queryset[: limit + 1])
    if len(rows) > limit:
        raise RegistrationTemplateValidationError
    return rows


def _locked_content(
    template: RegistrationTemplate,
) -> tuple[
    tuple[RegistrationTemplateSection, ...],
    tuple[RegistrationTemplateQuestion, ...],
    tuple[RegistrationTemplateProduct, ...],
    str,
]:
    sections = _bounded(
        RegistrationTemplateSection.objects.select_for_update()
        .filter(template=template)
        .order_by("position", "key", "id"),
        limit=MAX_TEMPLATE_SECTIONS,
    )
    questions = _bounded(
        RegistrationTemplateQuestion.objects.select_for_update()
        .filter(template=template)
        .order_by("position", "key", "id"),
        limit=MAX_TEMPLATE_QUESTIONS,
    )
    products = _bounded(
        RegistrationTemplateProduct.objects.select_for_update()
        .filter(template=template)
        .order_by("position", "code", "id"),
        limit=MAX_TEMPLATE_PRODUCTS,
    )
    typed_sections = tuple(sections)
    typed_questions = tuple(questions)
    typed_products = tuple(products)
    if not typed_products:
        raise RegistrationTemplateValidationError
    section_by_id = {section.id: section for section in typed_sections}
    prior_questions: dict[str, RegistrationTemplateQuestion] = {}
    try:
        template.full_clean()
        for section in typed_sections:
            section.full_clean()
        for question in typed_questions:
            question.full_clean()
        for product in typed_products:
            product.full_clean()
    except ValidationError as error:
        raise RegistrationTemplateValidationError from error
    for question in typed_questions:
        if len(question.help_text) > MAX_TEMPLATE_QUESTION_HELP_LENGTH or (
            question.section_id is not None and question.section_id not in section_by_id
        ):
            raise RegistrationTemplateValidationError
        if question.condition_question_key:
            source = prior_questions.get(question.condition_question_key)
            if (
                source is None
                or source.position >= question.position
                or not condition_value_is_compatible(
                    field_type=source.field_type,
                    options=source.options,
                    value=question.condition_value,
                )
            ):
                raise RegistrationTemplateValidationError
        prior_questions[question.key] = question
    if any(
        len(product.description) > MAX_TEMPLATE_PRODUCT_DESCRIPTION_LENGTH
        or (product.sales_open_at is None) != (product.sales_close_at is None)
        for product in typed_products
    ):
        raise RegistrationTemplateValidationError
    digest = template_content_digest(
        template=template,
        sections=typed_sections,
        questions=typed_questions,
        products=typed_products,
    )
    return typed_sections, typed_questions, typed_products, digest


def _request_digest(
    *,
    actor_id: UUID,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    template_id: UUID,
    expected_version: int,
    reason: str,
) -> str:
    action = RegistrationTemplateCatalogCommandReceipt.Action.TEMPLATE_PUBLISHED
    return canonical_digest(
        {
            "action": action,
            "actor_id": str(actor_id),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "template_id": str(template_id),
            "expected_version": expected_version,
            "reason": reason,
        }
    )


def require_published_template_evidence(
    template: RegistrationTemplate,
) -> RegistrationTemplateCatalogCommandReceipt:
    """Prove one published template's exact catalog/audit/event/outbox graph.

    Parameters
    ----------
    template : RegistrationTemplate
        The immutable starter or template used as the copy source.

    Returns
    -------
    RegistrationTemplateCatalogCommandReceipt
        The RegistrationTemplateCatalogCommandReceipt produced by require
        published template evidence.

    Raises
    ------
    RegistrationTemplateStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    if (
        template.status not in {TemplateStatus.PUBLISHED, TemplateStatus.RETIRED}
        or template.provenance_status != RegistrationProvenanceStatus.COMPLETE
        or template.published_at is None
        or template.created_in_catalog_version is None
        or template.last_changed_in_catalog_version is None
        or template.created_in_catalog_version
        != template.last_changed_in_catalog_version
        or _SHA256_PATTERN.fullmatch(template.content_digest) is None
    ):
        raise RegistrationTemplateStateConflictError
    catalog = RegistrationTemplateCatalogControl.objects.filter(
        organization_id=template.organization_id,
        provenance_status=RegistrationProvenanceStatus.COMPLETE,
        aggregate_version__gte=template.last_changed_in_catalog_version,
    ).first()
    if catalog is None:
        raise RegistrationTemplateStateConflictError
    receipts = tuple(
        RegistrationTemplateCatalogCommandReceipt.objects.filter(
            catalog=catalog,
            organization_id=template.organization_id,
            action=RegistrationTemplateCatalogCommandReceipt.Action.TEMPLATE_PUBLISHED,
            resulting_version=template.last_changed_in_catalog_version,
        )[:2]
    )
    if len(receipts) != 1:
        raise RegistrationTemplateStateConflictError
    receipt = receipts[0]
    targets = tuple(receipt.targets.order_by("target_kind", "target_id", "id")[:2])
    if (
        receipt.retry_key is None
        or _SHA256_PATTERN.fullmatch(receipt.request_digest) is None
        or len(targets) != 1
        or targets[0].target_kind
        != RegistrationTemplateCatalogCommandTarget.TargetKind.TEMPLATE
        or targets[0].target_id != template.id
        or targets[0].change_kind != RegistrationCommandChangeKind.PUBLISHED
        or targets[0].target_schema_version != template.version
        or targets[0].content_digest != template.content_digest
    ):
        raise RegistrationTemplateStateConflictError
    audits = tuple(
        AuditEvent.objects.filter(
            schema_version=1,
            organization_id=template.organization_id,
            principal_kind="account",
            principal_id=receipt.actor_id,
            capability_code="registration.manage_configuration",
            operation="registration.template.published",
            target_type="registration.template",
            target_id=template.id,
            outcome=AuditEvent.Outcome.ALLOW,
            correlation_id=receipt.correlation_id,
            source_channel=receipt.source_channel,
            changed_fields=[
                "catalog_versions",
                "content_digest",
                "provenance",
                "status",
            ],
            idempotency_key_hash=canonical_digest(
                {"retry_key": str(receipt.retry_key)}
            ),
            retention_class="registration-restricted",
        )[:2]
    )
    if len(audits) != 1:
        raise RegistrationTemplateStateConflictError
    audit = audits[0]
    if audit.event_edition_id is None:
        raise RegistrationTemplateStateConflictError
    authority_edition = EventEdition.objects.filter(
        pk=audit.event_edition_id,
        organization_id=template.organization_id,
    ).first()
    policy_version = audit.safe_metadata.get("policy_version")
    if (
        authority_edition is None
        or (
            template.series_id is not None
            and authority_edition.series_id != template.series_id
        )
        or template.published_at != audit.occurred_at
        or not audit.reason_code
        or audit.request_id is None
        or audit.obligations != sorted(set(audit.obligations))
        or set(audit.safe_metadata)
        != {"policy_version", "contract_version", "target_count"}
        or not isinstance(policy_version, str)
        or _POLICY_VERSION_PATTERN.fullmatch(policy_version) is None
        or audit.safe_metadata.get("contract_version")
        != "registration-template-publication-v1"
        or audit.safe_metadata.get("target_count") != 1
    ):
        raise RegistrationTemplateStateConflictError
    events = tuple(
        DomainEvent.objects.filter(
            event_name="registration.template.published.v1",
            schema_version=1,
            occurred_at=audit.occurred_at,
            organization_id=template.organization_id,
            event_edition_id=audit.event_edition_id,
            aggregate_type="registration.template_catalog",
            aggregate_id=catalog.id,
            aggregate_version=receipt.resulting_version,
            payload={
                "template_code": template.code,
                "template_version": str(template.version),
            },
            correlation_id=receipt.correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=receipt.actor_id,
            retention_class="registration-restricted",
        )[:2]
    )
    if len(events) != 1:
        raise RegistrationTemplateStateConflictError
    outbox = tuple(
        events[0].outbox_messages.filter(
            organization_id=template.organization_id,
            destination="internal",
            workload_pool="default",
        )[:2]
    )
    if len(outbox) != 1:
        raise RegistrationTemplateStateConflictError
    child_sets = (
        template.sections.all(),
        template.questions.all(),
        template.products.all(),
    )
    if any(
        queryset.exclude(
            created_in_catalog_version=receipt.resulting_version,
            last_changed_in_catalog_version=receipt.resulting_version,
        ).exists()
        for queryset in child_sets
    ):
        raise RegistrationTemplateStateConflictError
    return receipt


def _result_from_receipt(
    *,
    template: RegistrationTemplate,
    receipt: RegistrationTemplateCatalogCommandReceipt,
    request_digest: str,
) -> RegistrationTemplatePublishResult:
    if (
        receipt.action
        != RegistrationTemplateCatalogCommandReceipt.Action.TEMPLATE_PUBLISHED
        or receipt.request_digest != request_digest
    ):
        raise RegistrationTemplateRetryConflictError
    proven = require_published_template_evidence(template)
    if proven.id != receipt.id:
        raise RegistrationTemplateStateConflictError
    return RegistrationTemplatePublishResult(
        catalog_id=receipt.catalog_id,
        template_id=template.id,
        receipt_id=receipt.id,
        resulting_version=int(receipt.resulting_version),
        template_version=int(template.version),
        content_digest=template.content_digest,
        replayed=True,
    )


def publish_registration_template(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    template_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationTemplatePublishResult:
    """Publish one bounded draft through the organization catalog aggregate.

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
    template_id : UUID
        The template identifier within the requested scope.
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
    RegistrationTemplatePublishResult
        The RegistrationTemplatePublishResult produced by publish registration
        template.

    Raises
    ------
    RegistrationTemplateStateConflictError
        If the target lifecycle state does not permit the transition.
    RegistrationTemplateVersionConflictError
        If the supplied aggregate version is stale.
    """
    organization_id = _strict_uuid(organization_id, field="organization_id")
    series_id = _strict_uuid(series_id, field="series_id")
    edition_id = _strict_uuid(edition_id, field="edition_id")
    template_id = _strict_uuid(template_id, field="template_id")
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    if request_id is not None:
        request_id = _strict_uuid(request_id, field="request_id")
    expected_version = _expected_version(expected_version)
    reason = _normalized_reason(reason)
    source_channel = _source_channel(source_channel)
    _authorize(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    request_digest = _request_digest(
        actor_id=actor.id,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        template_id=template_id,
        expected_version=expected_version,
        reason=reason,
    )
    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            template_id=template_id,
        )
        replay = RegistrationTemplateCatalogCommandReceipt.objects.filter(
            organization=scope.organization,
            actor=scope.actor,
            retry_key=retry_key,
        ).first()
        if replay is not None:
            return _result_from_receipt(
                template=scope.template,
                receipt=replay,
                request_digest=request_digest,
            )
        current_version = int(scope.catalog.aggregate_version) if scope.catalog else 0
        if expected_version != current_version:
            raise RegistrationTemplateVersionConflictError
        if (
            scope.organization.lifecycle not in _EDITABLE_ORGANIZATION_LIFECYCLES
            or scope.edition.lifecycle not in _EDITABLE_EDITION_LIFECYCLES
            or scope.template.status != TemplateStatus.DRAFT
        ):
            raise RegistrationTemplateStateConflictError
        sections, questions, products, digest = _locked_content(scope.template)
        resulting_version = current_version + 1
        if scope.catalog is None:
            catalog = RegistrationTemplateCatalogControl.objects.create(
                organization=scope.organization,
                aggregate_version=resulting_version,
                provenance_status=RegistrationProvenanceStatus.COMPLETE,
            )
        else:
            catalog = scope.catalog
            catalog.aggregate_version = resulting_version
            catalog.provenance_status = RegistrationProvenanceStatus.COMPLETE
            catalog.save(
                update_fields=("aggregate_version", "provenance_status", "updated_at")
            )
        published_at = timezone.now()
        scope.template.status = TemplateStatus.PUBLISHED
        scope.template.published_at = published_at
        scope.template.provenance_status = RegistrationProvenanceStatus.COMPLETE
        scope.template.content_digest = digest
        scope.template.created_in_catalog_version = resulting_version
        scope.template.last_changed_in_catalog_version = resulting_version
        for queryset in (
            RegistrationTemplateSection.objects.filter(
                id__in=[item.id for item in sections]
            ),
            RegistrationTemplateQuestion.objects.filter(
                id__in=[item.id for item in questions]
            ),
            RegistrationTemplateProduct.objects.filter(
                id__in=[item.id for item in products]
            ),
        ):
            queryset.update(
                created_in_catalog_version=resulting_version,
                last_changed_in_catalog_version=resulting_version,
            )
        scope.template.save(
            update_fields=(
                "status",
                "published_at",
                "provenance_status",
                "content_digest",
                "created_in_catalog_version",
                "last_changed_in_catalog_version",
                "updated_at",
            )
        )
        receipt = RegistrationTemplateCatalogCommandReceipt.objects.create(
            catalog=catalog,
            organization=scope.organization,
            action=RegistrationTemplateCatalogCommandReceipt.Action.TEMPLATE_PUBLISHED,
            resulting_version=resulting_version,
            actor=scope.actor,
            reason=reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
            retry_key=retry_key,
            request_digest=request_digest,
        )
        RegistrationTemplateCatalogCommandTarget.objects.create(
            receipt=receipt,
            target_kind=RegistrationTemplateCatalogCommandTarget.TargetKind.TEMPLATE,
            target_id=scope.template.id,
            change_kind=RegistrationCommandChangeKind.PUBLISHED,
            target_schema_version=scope.template.version,
            content_digest=digest,
        )
        audit = append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=scope.actor.id,
                principal_context_id=None,
                organization_id=scope.organization.id,
                event_edition_id=scope.edition.id,
                capability_code="registration.manage_configuration",
                operation="registration.template.published",
                target_type="registration.template",
                target_id=scope.template.id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=scope.decision.reason_code,
                correlation_id=correlation_id,
                request_id=request_id or correlation_id,
                source_channel=source_channel,
                obligations=tuple(sorted(scope.decision.obligations)),
                changed_fields=(
                    "catalog_versions",
                    "content_digest",
                    "provenance",
                    "status",
                ),
                idempotency_key_hash=canonical_digest({"retry_key": str(retry_key)}),
                safe_metadata={
                    "policy_version": POLICY_VERSION,
                    "contract_version": "registration-template-publication-v1",
                    "target_count": 1,
                },
                retention_class="registration-restricted",
            ),
            occurred_at=published_at,
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="registration.template.published.v1",
                schema_version=1,
                organization_id=scope.organization.id,
                event_edition_id=scope.edition.id,
                aggregate_type="registration.template_catalog",
                aggregate_id=catalog.id,
                aggregate_version=resulting_version,
                payload={
                    "template_code": scope.template.code,
                    "template_version": str(scope.template.version),
                },
                correlation_id=correlation_id,
                causation_id=audit.id,
                actor_kind="account",
                actor_id=scope.actor.id,
                retention_class="registration-restricted",
            ),
            occurred_at=published_at,
        )
        require_published_template_evidence(scope.template)
        return RegistrationTemplatePublishResult(
            catalog_id=catalog.id,
            template_id=scope.template.id,
            receipt_id=receipt.id,
            resulting_version=resulting_version,
            template_version=int(scope.template.version),
            content_digest=digest,
            replayed=False,
        )


__all__ = [
    "RegistrationTemplateAuthorizationDeniedError",
    "RegistrationTemplateLifecycleError",
    "RegistrationTemplatePublishResult",
    "RegistrationTemplateRetryConflictError",
    "RegistrationTemplateStateConflictError",
    "RegistrationTemplateValidationError",
    "RegistrationTemplateVersionConflictError",
    "publish_registration_template",
    "require_published_template_evidence",
]
