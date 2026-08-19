"""Canonical Page 10 commands for draft registration sections."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Model, QuerySet
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision, decide, resolve_edition_target
from maru.core.validators import validate_lowercase_slug
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
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSetupCommandReceipt,
    RegistrationSetupCommandTarget,
    RegistrationSetupControl,
)
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
)
from maru.registration.setup_content import (
    canonical_digest,
    configuration_content_digest,
    section_payload,
    target_content_digest,
)

MAX_SECTION_KEY_LENGTH = 80
MAX_SECTION_TITLE_LENGTH = 160
MAX_SECTION_DESCRIPTION_LENGTH = 500
MAX_SECTION_REASON_LENGTH = 240
SECTION_POSITION_STEP = 10
MAX_SOURCE_CHANNEL_LENGTH = 32
_SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")
_EDITABLE_ORGANIZATION_LIFECYCLES = frozenset(
    {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
)
_EDITABLE_EDITION_LIFECYCLES = frozenset(
    {EventEdition.Lifecycle.DRAFT, EventEdition.Lifecycle.PREPARING}
)


class RegistrationSetupConfigurationUnavailableError(RegistrationSetupCommandError):
    reason_code = "registration_setup_configuration_unavailable"


class RegistrationSetupSectionUnavailableError(RegistrationSetupCommandError):
    reason_code = "registration_setup_section_unavailable"


class RegistrationSetupSectionDependencyError(RegistrationSetupCommandError):
    reason_code = "registration_setup_section_has_dependencies"


@dataclass(frozen=True, slots=True)
class RegistrationSectionCommandResult:
    setup_id: UUID
    configuration_id: UUID
    receipt_id: UUID
    section_id: UUID
    resulting_version: int
    action: str
    configuration_content_digest: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class _SectionTargetEvidence:
    section_id: UUID
    change_kind: str
    content_digest: str


@dataclass(frozen=True, slots=True)
class _LockedSectionScope:
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
    decision: PolicyDecision
    evaluated_at: datetime


class _VersionedSetupScope(Protocol):
    @property
    def organization(self) -> Organization: ...

    @property
    def edition(self) -> EventEdition: ...

    @property
    def actor(self) -> Account: ...

    @property
    def control(self) -> RegistrationSetupControl: ...


def _field_error(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: ValidationError(message, code=code)})


def _authorize_before_input_parsing(
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
        raise RegistrationSetupAuthorizationDeniedError()
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if target is None:
        raise RegistrationSetupAuthorizationDeniedError()
    decision = decide(
        principal=actor,
        capability_code="registration.manage_configuration",
        resource=target,
        at=at,
    )
    if not decision.allowed:
        raise RegistrationSetupAuthorizationDeniedError()
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


def _normalized_required_text(
    value: object,
    *,
    field: str,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise _field_error(
            field,
            "Enter text.",
            "registration_setup_text_invalid",
        )
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if not normalized:
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


def _normalized_optional_text(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise _field_error(
            field,
            "Enter text.",
            "registration_setup_text_invalid",
        )
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
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


def _normalized_key(value: object) -> str:
    if not isinstance(value, str):
        raise _field_error(
            "key",
            "Enter a lowercase section key.",
            "registration_setup_section_key_invalid",
        )
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > MAX_SECTION_KEY_LENGTH:
        raise _field_error(
            "key",
            "Use a section key of 1 through 80 characters.",
            "registration_setup_section_key_invalid",
        )
    try:
        validate_lowercase_slug(normalized)
    except ValidationError as error:
        raise _field_error(
            "key",
            "Use lowercase letters, numbers, and single hyphens only.",
            "registration_setup_section_key_invalid",
        ) from error
    return normalized


def _bounded[ItemT: Model](
    queryset: QuerySet[ItemT], *, limit: int
) -> tuple[ItemT, ...]:
    rows = tuple(queryset[: limit + 1])
    if len(rows) > limit:
        raise RegistrationSetupLimitExceededError()
    return rows


def _lock_scope(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
) -> _LockedSectionScope:
    organization = (
        Organization.objects.select_for_update().filter(pk=organization_id).first()
    )
    if organization is None:
        raise RegistrationSetupAuthorizationDeniedError()
    series = (
        ConventionSeries.objects.select_for_update()
        .filter(pk=series_id, organization_id=organization.id)
        .first()
    )
    if series is None:
        raise RegistrationSetupAuthorizationDeniedError()
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
        raise RegistrationSetupAuthorizationDeniedError()
    control = (
        RegistrationSetupControl.objects.select_for_update()
        .filter(
            organization_id=organization.id,
            edition_id=edition.id,
        )
        .first()
    )
    if control is None:
        raise RegistrationSetupStateConflictError()
    persisted_actor = Account.objects.select_for_update().filter(pk=actor.pk).first()
    if persisted_actor is None:
        raise RegistrationSetupAuthorizationDeniedError()
    evaluated_at = timezone.now()
    decision = _authorize_before_input_parsing(
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
            organization_id=organization.id,
            edition_id=edition.id,
        )
        .first()
    )
    if configuration is None:
        raise RegistrationSetupConfigurationUnavailableError()
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
    products = _bounded(
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
    return _LockedSectionScope(
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
        decision=decision,
        evaluated_at=evaluated_at,
    )


def _require_editable_draft(scope: _LockedSectionScope) -> None:
    if (
        scope.organization.lifecycle not in _EDITABLE_ORGANIZATION_LIFECYCLES
        or scope.edition.lifecycle not in _EDITABLE_EDITION_LIFECYCLES
        or scope.configuration.status != ConfigurationStatus.DRAFT
    ):
        raise RegistrationSetupLifecycleConflictError()


def _require_current_version(scope: _VersionedSetupScope, expected_version: int) -> int:
    current_version = int(scope.control.aggregate_version)
    if current_version != expected_version:
        raise RegistrationSetupVersionConflictError()
    return current_version


def _configuration_digest(
    scope: _LockedSectionScope,
    *,
    sections: tuple[RegistrationSection, ...],
) -> str:
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
        sections=sections,
        questions=scope.questions,
        products=scope.products,
        minor_policy=scope.minor_policy,
    )


def _require_current_digest(scope: _LockedSectionScope) -> None:
    current = _configuration_digest(scope, sections=scope.sections)
    if scope.configuration.content_digest and (
        scope.configuration.content_digest != current
    ):
        raise RegistrationSetupDependencyError()


def _receipt_for_retry(
    *,
    scope: _VersionedSetupScope,
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
    scope: _LockedSectionScope,
    receipt: RegistrationSetupCommandReceipt,
    action: str,
    request_digest: str,
    section_id: UUID | None,
) -> RegistrationSectionCommandResult:
    if receipt.action != action or receipt.request_digest != request_digest:
        raise RegistrationSetupRetryConflictError()
    configuration_target = receipt.targets.filter(
        target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
        target_id=scope.configuration.id,
        change_kind=RegistrationCommandChangeKind.UPDATED,
    ).first()
    section_targets = receipt.targets.filter(
        target_kind=RegistrationSetupCommandTarget.TargetKind.SECTION,
    )
    section_target = (
        section_targets.filter(target_id=section_id).first()
        if section_id is not None
        else section_targets.filter(
            change_kind=RegistrationCommandChangeKind.CREATED,
        ).first()
    )
    if configuration_target is None or section_target is None:
        raise RegistrationSetupStateConflictError()
    return RegistrationSectionCommandResult(
        setup_id=receipt.setup_id,
        configuration_id=scope.configuration.id,
        receipt_id=receipt.id,
        section_id=section_target.target_id,
        resulting_version=int(receipt.resulting_version),
        action=receipt.action,
        configuration_content_digest=configuration_target.content_digest,
        replayed=True,
    )


def _section_by_id(
    scope: _LockedSectionScope,
    section_id: UUID,
) -> RegistrationSection:
    section = next((item for item in scope.sections if item.id == section_id), None)
    if section is None:
        raise RegistrationSetupSectionUnavailableError()
    return section


def _ordered_after(
    *,
    sections: tuple[RegistrationSection, ...],
    section: RegistrationSection,
    after_section_id: UUID | None,
) -> tuple[RegistrationSection, ...]:
    remaining = [item for item in sections if item.id != section.id]
    if after_section_id == section.id:
        raise _field_error(
            "after_section_id",
            "Choose another section as the ordering anchor.",
            "registration_setup_section_move_invalid",
        )
    if after_section_id is None:
        insertion_index = 0
    else:
        anchor_index = next(
            (
                index
                for index, item in enumerate(remaining)
                if item.id == after_section_id
            ),
            None,
        )
        if anchor_index is None:
            raise RegistrationSetupSectionUnavailableError()
        insertion_index = anchor_index + 1
    remaining.insert(insertion_index, section)
    return tuple(remaining)


def _renumber_sections(
    sections: tuple[RegistrationSection, ...],
    *,
    resulting_version: int,
    changed_at: datetime,
) -> tuple[RegistrationSection, ...]:
    changed: list[RegistrationSection] = []
    for index, section in enumerate(sections, start=1):
        expected_position = index * SECTION_POSITION_STEP
        if section.position == expected_position:
            continue
        section.position = expected_position
        section.last_changed_in_setup_version = resulting_version
        section.updated_at = changed_at
        if not section._state.adding:
            changed.append(section)
    return tuple(changed)


def _persist_renumbered_sections(
    sections: tuple[RegistrationSection, ...],
) -> None:
    if sections:
        RegistrationSection.objects.bulk_update(
            sections,
            fields=("position", "last_changed_in_setup_version", "updated_at"),
        )


def _advance_configuration(
    *,
    scope: _LockedSectionScope,
    sections: tuple[RegistrationSection, ...],
    resulting_version: int,
) -> str:
    digest = _configuration_digest(scope, sections=sections)
    scope.configuration.content_digest = digest
    scope.configuration.last_changed_in_setup_version = resulting_version
    scope.configuration.save(
        update_fields=(
            "content_digest",
            "last_changed_in_setup_version",
            "updated_at",
        )
    )
    scope.control.aggregate_version = resulting_version
    scope.control.save(update_fields=("aggregate_version", "updated_at"))
    return digest


def _append_evidence(
    *,
    scope: _LockedSectionScope,
    action: str,
    resulting_version: int,
    primary_section_id: UUID,
    section_targets: tuple[_SectionTargetEvidence, ...],
    configuration_digest: str,
    changed_fields: tuple[str, ...],
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
        change_kind=RegistrationCommandChangeKind.UPDATED,
        target_schema_version=scope.configuration.version,
        content_digest=configuration_digest,
    )
    for target in section_targets:
        RegistrationSetupCommandTarget.objects.create(
            receipt=receipt,
            target_kind=RegistrationSetupCommandTarget.TargetKind.SECTION,
            target_id=target.section_id,
            change_kind=target.change_kind,
            content_digest=target.content_digest,
        )
    audit_event = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor.id,
            principal_context_id=None,
            organization_id=scope.organization.id,
            event_edition_id=scope.edition.id,
            capability_code="registration.manage_configuration",
            operation="registration.setup.section.changed",
            target_type="registration.section",
            target_id=primary_section_id,
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
                "contract_version": "registration-section-command-v1",
                "target_count": 1 + len(section_targets),
            },
            retention_class="registration-restricted",
        ),
        occurred_at=scope.evaluated_at,
    )
    publish_domain_event(
        DomainEventRecord(
            event_name="registration.configuration.draft_changed.v1",
            schema_version=1,
            organization_id=scope.organization.id,
            event_edition_id=scope.edition.id,
            aggregate_type="registration.setup",
            aggregate_id=scope.control.id,
            aggregate_version=resulting_version,
            payload={
                "action": action,
                "configuration_version": str(scope.configuration.version),
            },
            correlation_id=correlation_id,
            causation_id=audit_event.id,
            actor_kind="account",
            actor_id=scope.actor.id,
            retention_class="registration-restricted",
        ),
        occurred_at=scope.evaluated_at,
    )
    return receipt


def _result(
    *,
    scope: _LockedSectionScope,
    receipt: RegistrationSetupCommandReceipt,
    section_id: UUID,
    configuration_digest: str,
) -> RegistrationSectionCommandResult:
    return RegistrationSectionCommandResult(
        setup_id=scope.control.id,
        configuration_id=scope.configuration.id,
        receipt_id=receipt.id,
        section_id=section_id,
        resulting_version=int(receipt.resulting_version),
        action=receipt.action,
        configuration_content_digest=configuration_digest,
        replayed=False,
    )


def _delete_without_cascade(section: RegistrationSection) -> None:
    try:
        with transaction.atomic():
            deleted_count, _detail = section.delete()
    except (ProtectedError, RestrictedError) as error:
        raise RegistrationSetupSectionDependencyError() from error
    except IntegrityError as error:
        cause = error.__cause__
        if getattr(cause, "sqlstate", None) == "23503":
            raise RegistrationSetupSectionDependencyError() from error
        raise
    if deleted_count != 1:
        raise RegistrationSetupSectionDependencyError()


def create_registration_section(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    key: str,
    title: str,
    description: str,
    after_section_id: UUID | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationSectionCommandResult:
    """Create one section and place it after one exact bounded sibling."""

    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    normalized_key = _normalized_key(key)
    normalized_title = _normalized_required_text(
        title,
        field="title",
        maximum=MAX_SECTION_TITLE_LENGTH,
    )
    normalized_description = _normalized_optional_text(
        description,
        field="description",
        maximum=MAX_SECTION_DESCRIPTION_LENGTH,
    )
    if after_section_id is not None:
        after_section_id = _strict_uuid(
            after_section_id,
            field="after_section_id",
        )
    expected_version = _expected_version(expected_version)
    normalized_reason = _normalized_required_text(
        reason,
        field="reason",
        maximum=MAX_SECTION_REASON_LENGTH,
    )
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    if request_id is not None:
        request_id = _strict_uuid(request_id, field="request_id")
    source_channel = _source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "action": RegistrationSetupCommandReceipt.Action.SECTION_CREATED,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "key": normalized_key,
            "title": normalized_title,
            "description": normalized_description,
            "after_section_id": (
                str(after_section_id) if after_section_id is not None else None
            ),
            "expected_version": expected_version,
            "reason": normalized_reason,
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
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=RegistrationSetupCommandReceipt.Action.SECTION_CREATED,
                request_digest=request_digest,
                section_id=None,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        if len(scope.sections) >= MAX_SETUP_SECTIONS:
            raise RegistrationSetupLimitExceededError()
        if any(section.key == normalized_key for section in scope.sections):
            raise _field_error(
                "key",
                "This configuration already has that section key.",
                "registration_setup_section_key_duplicate",
            )
        resulting_version = current_version + 1
        section = RegistrationSection(
            configuration=scope.configuration,
            key=normalized_key,
            title=normalized_title,
            description=normalized_description,
            position=0,
            created_in_setup_version=resulting_version,
            last_changed_in_setup_version=resulting_version,
        )
        ordered = _ordered_after(
            sections=scope.sections,
            section=section,
            after_section_id=after_section_id,
        )
        changed = _renumber_sections(
            ordered,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        section.full_clean()
        section.save(force_insert=True)
        _persist_renumbered_sections(changed)
        configuration_digest = _advance_configuration(
            scope=scope,
            sections=ordered,
            resulting_version=resulting_version,
        )
        section_targets = (
            _SectionTargetEvidence(
                section_id=section.id,
                change_kind=RegistrationCommandChangeKind.CREATED,
                content_digest=target_content_digest(
                    kind="section",
                    payload=section_payload(section),
                ),
            ),
            *(
                _SectionTargetEvidence(
                    section_id=moved.id,
                    change_kind=RegistrationCommandChangeKind.MOVED,
                    content_digest=target_content_digest(
                        kind="section",
                        payload=section_payload(moved),
                    ),
                )
                for moved in changed
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=RegistrationSetupCommandReceipt.Action.SECTION_CREATED,
            resulting_version=resulting_version,
            primary_section_id=section.id,
            section_targets=section_targets,
            configuration_digest=configuration_digest,
            changed_fields=("sections", "section_order"),
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        return _result(
            scope=scope,
            receipt=receipt,
            section_id=section.id,
            configuration_digest=configuration_digest,
        )


def update_registration_section(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    section_id: UUID,
    key: str,
    title: str,
    description: str,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationSectionCommandResult:
    """Completely replace one draft section's editable properties."""

    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    section_id = _strict_uuid(section_id, field="section_id")
    normalized_key = _normalized_key(key)
    normalized_title = _normalized_required_text(
        title,
        field="title",
        maximum=MAX_SECTION_TITLE_LENGTH,
    )
    normalized_description = _normalized_optional_text(
        description,
        field="description",
        maximum=MAX_SECTION_DESCRIPTION_LENGTH,
    )
    expected_version = _expected_version(expected_version)
    normalized_reason = _normalized_required_text(
        reason,
        field="reason",
        maximum=MAX_SECTION_REASON_LENGTH,
    )
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    if request_id is not None:
        request_id = _strict_uuid(request_id, field="request_id")
    source_channel = _source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "action": RegistrationSetupCommandReceipt.Action.SECTION_UPDATED,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "section_id": str(section_id),
            "key": normalized_key,
            "title": normalized_title,
            "description": normalized_description,
            "expected_version": expected_version,
            "reason": normalized_reason,
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
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=RegistrationSetupCommandReceipt.Action.SECTION_UPDATED,
                request_digest=request_digest,
                section_id=section_id,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        section = _section_by_id(scope, section_id)
        if any(
            item.id != section.id and item.key == normalized_key
            for item in scope.sections
        ):
            raise _field_error(
                "key",
                "This configuration already has that section key.",
                "registration_setup_section_key_duplicate",
            )
        changed_fields = tuple(
            field
            for field, changed in (
                ("key", section.key != normalized_key),
                ("title", section.title != normalized_title),
                ("description", section.description != normalized_description),
            )
            if changed
        )
        if not changed_fields:
            raise RegistrationSetupStateConflictError()
        resulting_version = current_version + 1
        section.key = normalized_key
        section.title = normalized_title
        section.description = normalized_description
        section.last_changed_in_setup_version = resulting_version
        section.save(
            update_fields=(
                "key",
                "title",
                "description",
                "last_changed_in_setup_version",
                "updated_at",
            )
        )
        configuration_digest = _advance_configuration(
            scope=scope,
            sections=scope.sections,
            resulting_version=resulting_version,
        )
        receipt = _append_evidence(
            scope=scope,
            action=RegistrationSetupCommandReceipt.Action.SECTION_UPDATED,
            resulting_version=resulting_version,
            primary_section_id=section.id,
            section_targets=(
                _SectionTargetEvidence(
                    section_id=section.id,
                    change_kind=RegistrationCommandChangeKind.UPDATED,
                    content_digest=target_content_digest(
                        kind="section",
                        payload=section_payload(section),
                    ),
                ),
            ),
            configuration_digest=configuration_digest,
            changed_fields=changed_fields,
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        return _result(
            scope=scope,
            receipt=receipt,
            section_id=section.id,
            configuration_digest=configuration_digest,
        )


def move_registration_section(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    section_id: UUID,
    after_section_id: UUID | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationSectionCommandResult:
    """Move one draft section after an exact sibling, or first when absent."""

    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    section_id = _strict_uuid(section_id, field="section_id")
    if after_section_id is not None:
        after_section_id = _strict_uuid(
            after_section_id,
            field="after_section_id",
        )
    expected_version = _expected_version(expected_version)
    normalized_reason = _normalized_required_text(
        reason,
        field="reason",
        maximum=MAX_SECTION_REASON_LENGTH,
    )
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    if request_id is not None:
        request_id = _strict_uuid(request_id, field="request_id")
    source_channel = _source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "action": RegistrationSetupCommandReceipt.Action.SECTION_MOVED,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "section_id": str(section_id),
            "after_section_id": (
                str(after_section_id) if after_section_id is not None else None
            ),
            "expected_version": expected_version,
            "reason": normalized_reason,
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
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=RegistrationSetupCommandReceipt.Action.SECTION_MOVED,
                request_digest=request_digest,
                section_id=section_id,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        section = _section_by_id(scope, section_id)
        ordered = _ordered_after(
            sections=scope.sections,
            section=section,
            after_section_id=after_section_id,
        )
        if tuple(item.id for item in ordered) == tuple(
            item.id for item in scope.sections
        ):
            raise RegistrationSetupStateConflictError()
        resulting_version = current_version + 1
        changed = _renumber_sections(
            ordered,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        if all(item.id != section.id for item in changed):
            section.last_changed_in_setup_version = resulting_version
            section.updated_at = scope.evaluated_at
            changed = (*changed, section)
        _persist_renumbered_sections(changed)
        configuration_digest = _advance_configuration(
            scope=scope,
            sections=ordered,
            resulting_version=resulting_version,
        )
        receipt = _append_evidence(
            scope=scope,
            action=RegistrationSetupCommandReceipt.Action.SECTION_MOVED,
            resulting_version=resulting_version,
            primary_section_id=section.id,
            section_targets=tuple(
                _SectionTargetEvidence(
                    section_id=moved.id,
                    change_kind=RegistrationCommandChangeKind.MOVED,
                    content_digest=target_content_digest(
                        kind="section",
                        payload=section_payload(moved),
                    ),
                )
                for moved in changed
            ),
            configuration_digest=configuration_digest,
            changed_fields=("section_order",),
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        return _result(
            scope=scope,
            receipt=receipt,
            section_id=section.id,
            configuration_digest=configuration_digest,
        )


def delete_registration_section(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    section_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationSectionCommandResult:
    """Delete one unreferenced draft section and completely renumber siblings."""

    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    section_id = _strict_uuid(section_id, field="section_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _normalized_required_text(
        reason,
        field="reason",
        maximum=MAX_SECTION_REASON_LENGTH,
    )
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    if request_id is not None:
        request_id = _strict_uuid(request_id, field="request_id")
    source_channel = _source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "action": RegistrationSetupCommandReceipt.Action.SECTION_DELETED,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "section_id": str(section_id),
            "expected_version": expected_version,
            "reason": normalized_reason,
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
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=RegistrationSetupCommandReceipt.Action.SECTION_DELETED,
                request_digest=request_digest,
                section_id=section_id,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        section = _section_by_id(scope, section_id)
        if any(question.section_id == section.id for question in scope.questions):
            raise RegistrationSetupSectionDependencyError()
        resulting_version = current_version + 1
        deleted_digest = target_content_digest(
            kind="section",
            payload=section_payload(section),
        )
        remaining = tuple(item for item in scope.sections if item.id != section.id)
        _delete_without_cascade(section)
        changed = _renumber_sections(
            remaining,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        _persist_renumbered_sections(changed)
        configuration_digest = _advance_configuration(
            scope=scope,
            sections=remaining,
            resulting_version=resulting_version,
        )
        receipt = _append_evidence(
            scope=scope,
            action=RegistrationSetupCommandReceipt.Action.SECTION_DELETED,
            resulting_version=resulting_version,
            primary_section_id=section_id,
            section_targets=(
                _SectionTargetEvidence(
                    section_id=section_id,
                    change_kind=RegistrationCommandChangeKind.DELETED,
                    content_digest=deleted_digest,
                ),
                *(
                    _SectionTargetEvidence(
                        section_id=moved.id,
                        change_kind=RegistrationCommandChangeKind.MOVED,
                        content_digest=target_content_digest(
                            kind="section",
                            payload=section_payload(moved),
                        ),
                    )
                    for moved in changed
                ),
            ),
            configuration_digest=configuration_digest,
            changed_fields=("sections", "section_order"),
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        return _result(
            scope=scope,
            receipt=receipt,
            section_id=section_id,
            configuration_digest=configuration_digest,
        )
