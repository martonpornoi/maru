"""Governed Page 10 commands for registration-definition records.

The browser and API adapters are intentionally thin.  Every mutation in this
module resolves the exact edition authority before parsing caller-controlled
fields, locks the complete bounded setup aggregate, verifies optimistic and
idempotency evidence, and appends audit plus outbox evidence atomically.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from maru.participation.models import ParticipationCapacity
from maru.registration.models import (
    AdmissionProduct,
    MinorRegistrationPolicy,
    ProfileExtensionAudience,
    ProfileExtensionReviewStatus,
    ProfileExtensionStatus,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    QuestionVisibility,
    RegistrationCommandChangeKind,
    RegistrationProfileExtensionField,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSetupCommandReceipt,
    RegistrationSetupCommandTarget,
    RegistrationSetupControl,
    RegistrationSubmission,
)
from maru.registration.question_conditions import condition_value_is_compatible
from maru.registration.setup_commands import (
    MAX_PAYMENT_WINDOW_MINUTES,
    MAX_SETUP_CAPACITY,
    MAX_SETUP_PRODUCTS,
    MAX_SETUP_QUESTIONS,
    MIN_PAYMENT_WINDOW_MINUTES,
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupCommandError,
    RegistrationSetupLifecycleConflictError,
    RegistrationSetupLimitExceededError,
    RegistrationSetupRetryConflictError,
    RegistrationSetupStateConflictError,
)
from maru.registration.setup_content import (
    canonical_digest,
    configuration_content_digest,
    minor_policy_payload,
    product_payload,
    profile_extension_payload,
    question_payload,
    target_content_digest,
)
from maru.registration.setup_evidence import (
    require_setup_command_evidence_graph,
    target_expectation,
)
from maru.registration.setup_section_commands import (
    _authorize_before_input_parsing,
    _expected_version,
    _lock_scope,
    _normalized_optional_text,
    _normalized_required_text,
    _receipt_for_retry,
    _require_current_digest,
    _require_current_version,
    _require_editable_draft,
    _source_channel,
    _strict_uuid,
)

if TYPE_CHECKING:
    from uuid import UUID

    from maru.authorization.policy import PolicyDecision

MAX_QUESTION_LABEL_LENGTH = 200
MAX_QUESTION_HELP_LENGTH = 2_000
MAX_QUESTION_PURPOSE_LENGTH = 240
MAX_QUESTION_OPTION_LENGTH = 120
MAX_QUESTION_OPTIONS = 64
MINIMUM_CHOICE_OPTIONS = 2
MAX_CONDITION_VALUE_LENGTH = 120
MAX_PRODUCT_CODE_LENGTH = 80
MAX_PRODUCT_NAME_LENGTH = 160
MAX_PRODUCT_DESCRIPTION_LENGTH = 2_000
MAX_PRODUCT_ELIGIBILITY_LENGTH = 240
MAX_PRODUCT_PRICE_MINOR = 1_000_000_000_000
MAX_PRODUCT_CAPACITY_CODES = 32
MAX_PROFILE_FIELDS = 128
MAX_MINOR_NOTICE_VERSION_LENGTH = 40
MAX_MINOR_JURISDICTION_LENGTH = 40
MAX_MINOR_REVIEW_REFERENCE_LENGTH = 120
MAX_DEFINITION_REASON_LENGTH = 240
ORDER_POSITION_STEP = 10
MAX_PROFILE_ACTIVATION_TARGETS = 2

_QUESTION_TYPES = frozenset(QuestionFieldType.values)
_QUESTION_VISIBILITIES = frozenset(QuestionVisibility.values)
_QUESTION_CLASSIFICATIONS = frozenset(QuestionClassification.values)
_PROFILE_AUDIENCES = frozenset(ProfileExtensionAudience.values)
_PROFILE_WRITERS = frozenset(ProfileExtensionWriter.values)
_PRODUCT_STATUSES = frozenset(AdmissionProduct.Status.values)
_CHOICE_TYPES = frozenset(
    {QuestionFieldType.SINGLE_CHOICE, QuestionFieldType.MULTIPLE_CHOICE}
)
_RESERVED_PROFILE_PREFIXES = (
    "infinity",
    "admission",
    "entitlement",
    "payment",
    "role",
    "capacity",
    "restriction",
)


class RegistrationSetupQuestionUnavailableError(RegistrationSetupCommandError):
    """Signal registration setup question unavailable."""

    reason_code = "registration_setup_question_unavailable"


class RegistrationSetupQuestionDependencyError(RegistrationSetupCommandError):
    """Signal registration setup question dependency."""

    reason_code = "registration_setup_question_has_dependencies"


class RegistrationSetupProductUnavailableError(RegistrationSetupCommandError):
    """Signal registration setup product unavailable."""

    reason_code = "registration_setup_product_unavailable"


class RegistrationSetupProductDependencyError(RegistrationSetupCommandError):
    """Signal registration setup product dependency."""

    reason_code = "registration_setup_product_has_dependencies"


class RegistrationSetupMinorPolicyUnavailableError(RegistrationSetupCommandError):
    """Signal registration setup minor policy unavailable."""

    reason_code = "registration_setup_minor_policy_unavailable"


class RegistrationSetupMinorPolicyDependencyError(RegistrationSetupCommandError):
    """Signal registration setup minor policy dependency."""

    reason_code = "registration_setup_minor_policy_has_dependencies"


class RegistrationSetupProfileFieldUnavailableError(RegistrationSetupCommandError):
    """Signal registration setup profile field unavailable."""

    reason_code = "registration_setup_profile_field_unavailable"


class RegistrationSetupProfileFieldImmutableError(RegistrationSetupCommandError):
    """Signal registration setup profile field immutable."""

    reason_code = "registration_setup_profile_field_immutable"


class RegistrationSetupProfileFieldDependencyError(RegistrationSetupCommandError):
    """Signal registration setup profile field dependency."""

    reason_code = "registration_setup_profile_field_has_successor"


class RegistrationSetupProfileFieldReviewRequiredError(RegistrationSetupCommandError):
    """Signal registration setup profile field review required."""

    reason_code = "registration_setup_profile_field_review_required"


class RegistrationSetupProfileFieldSuccessorConflictError(
    RegistrationSetupCommandError
):
    """Signal registration setup profile field successor conflict."""

    reason_code = "registration_setup_profile_field_successor_conflict"


@dataclass(frozen=True, slots=True)
class RegistrationDefinitionCommandResult:
    """Describe registration definition command result.

    Attributes
    ----------
    setup_id
        The setup identifier within the requested scope.
    receipt_id
        The receipt identifier within the requested scope.
    target_id
        The target identifier within the requested scope.
    resulting_version
        The expected resulting version used to reject stale updates.
    action
        The stable action code describing the requested transition.
    configuration_id
        The configuration identifier within the requested scope.
    configuration_content_digest
        The canonical digest used to verify configuration content.
    replayed
        The replayed retained in this immutable projection.
    """

    setup_id: UUID
    receipt_id: UUID
    target_id: UUID
    resulting_version: int
    action: str
    configuration_id: UUID | None
    configuration_content_digest: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class _TargetEvidence:
    target_kind: str
    target_id: UUID
    change_kind: str
    content_digest: str
    target_schema_version: int | None = None


@dataclass(frozen=True, slots=True)
class _LockedProfileScope:
    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    actor: Account
    control: RegistrationSetupControl
    fields: tuple[RegistrationProfileExtensionField, ...]
    decision: PolicyDecision
    evaluated_at: datetime


def _field_error(field: str, message: str, code: str) -> ValidationError:
    return ValidationError({field: ValidationError(message, code=code)})


def _strict_boolean(value: object, *, field: str) -> bool:
    if type(value) is not bool:
        raise _field_error(
            field,
            "Choose yes or no.",
            "registration_setup_boolean_invalid",
        )
    return value


def _strict_integer(
    value: object,
    *,
    field: str,
    minimum: int,
    maximum: int,
    optional: bool = False,
) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or value < minimum or value > maximum:
        raise _field_error(
            field,
            f"Enter a whole number from {minimum} through {maximum}.",
            "registration_setup_integer_invalid",
        )
    return value


def _closed_choice(
    value: object,
    *,
    field: str,
    choices: frozenset[str],
) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _field_error(
            field,
            "Choose one documented value.",
            "registration_setup_choice_invalid",
        )
    return value


def _normalized_key(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise _field_error(
            field,
            "Enter a lowercase stable key.",
            "registration_setup_key_invalid",
        )
    normalized = unicodedata.normalize("NFC", value).strip()
    if (
        not normalized
        or len(normalized) > MAX_PRODUCT_CODE_LENGTH
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized) is None
    ):
        raise _field_error(
            field,
            "Use 1 through 80 lowercase letters, numbers, and single hyphens.",
            "registration_setup_key_invalid",
        )
    return normalized


def _normalized_options(value: object) -> list[str]:
    if not isinstance(value, list):
        raise _field_error(
            "options",
            "Provide a list of option labels.",
            "registration_setup_question_options_invalid",
        )
    if len(value) > MAX_QUESTION_OPTIONS:
        raise RegistrationSetupLimitExceededError
    normalized = [
        _normalized_required_text(
            option,
            field="options",
            maximum=MAX_QUESTION_OPTION_LENGTH,
        )
        for option in value
    ]
    if len(set(normalized)) != len(normalized):
        raise _field_error(
            "options",
            "Option labels must be unique.",
            "registration_setup_question_options_duplicate",
        )
    return normalized


def _validate_options_for_type(*, field_type: str, options: list[str]) -> None:
    if field_type in _CHOICE_TYPES and len(options) < MINIMUM_CHOICE_OPTIONS:
        raise _field_error(
            "options",
            "Choice questions require at least two options.",
            "registration_setup_question_options_required",
        )
    if field_type not in _CHOICE_TYPES and options:
        raise _field_error(
            "options",
            "Only choice questions may define options.",
            "registration_setup_question_options_not_allowed",
        )


def _strict_optional_uuid(value: object, *, field: str) -> UUID | None:
    if value is None:
        return None
    return _strict_uuid(value, field=field)


def _aware_datetime(value: object, *, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise _field_error(
            field,
            "Enter an aware date and time.",
            "registration_setup_datetime_invalid",
        )
    return value


def _reason(value: object) -> str:
    return _normalized_required_text(
        value,
        field="reason",
        maximum=MAX_DEFINITION_REASON_LENGTH,
    )


def _configuration_digest(
    scope: Any,
    *,
    questions: tuple[RegistrationQuestion, ...] | None = None,
    products: tuple[AdmissionProduct, ...] | None = None,
    minor_policy: MinorRegistrationPolicy | None | object = ...,
) -> str:
    configuration = scope.configuration
    policy = scope.minor_policy if minor_policy is ... else minor_policy
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
        questions=questions if questions is not None else scope.questions,
        products=products if products is not None else scope.products,
        minor_policy=policy,
    )


def _advance_configuration(
    *,
    scope: Any,
    resulting_version: int,
    questions: tuple[RegistrationQuestion, ...] | None = None,
    products: tuple[AdmissionProduct, ...] | None = None,
    minor_policy: MinorRegistrationPolicy | None | object = ...,
) -> str:
    digest = _configuration_digest(
        scope,
        questions=questions,
        products=products,
        minor_policy=minor_policy,
    )
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
    scope: Any,
    action: str,
    resulting_version: int,
    primary: _TargetEvidence,
    targets: tuple[_TargetEvidence, ...],
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
    if configuration_digest:
        RegistrationSetupCommandTarget.objects.create(
            receipt=receipt,
            target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
            target_id=scope.configuration.id,
            change_kind=RegistrationCommandChangeKind.UPDATED,
            target_schema_version=scope.configuration.version,
            content_digest=configuration_digest,
        )
    for target in targets:
        RegistrationSetupCommandTarget.objects.create(
            receipt=receipt,
            target_kind=target.target_kind,
            target_id=target.target_id,
            change_kind=target.change_kind,
            target_schema_version=target.target_schema_version,
            content_digest=target.content_digest,
        )
    operation_segment_by_kind: dict[str, str] = {
        RegistrationSetupCommandTarget.TargetKind.QUESTION: "question",
        RegistrationSetupCommandTarget.TargetKind.PRODUCT: "product",
        RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY: "minor_policy",
        RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD: "profile_field",
    }
    operation_segment = operation_segment_by_kind[primary.target_kind]
    audit_event = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor.id,
            principal_context_id=None,
            organization_id=scope.organization.id,
            event_edition_id=scope.edition.id,
            capability_code="registration.manage_configuration",
            operation=f"registration.setup.{operation_segment}.changed",
            target_type=f"registration.{operation_segment}",
            target_id=primary.target_id,
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
                "contract_version": "registration-definition-command-v1",
                "target_count": len(targets) + int(bool(configuration_digest)),
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
                "configuration_version": (
                    str(scope.configuration.version)
                    if configuration_digest
                    else "profile-extensions"
                ),
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


def _result_from_receipt(
    *,
    scope: Any,
    receipt: RegistrationSetupCommandReceipt,
    action: str,
    request_digest: str,
    target_kind: str,
    target_id: UUID | None,
) -> RegistrationDefinitionCommandResult:
    if receipt.action != action or receipt.request_digest != request_digest:
        raise RegistrationSetupRetryConflictError
    candidates = receipt.targets.filter(target_kind=target_kind)
    target = (
        candidates.filter(target_id=target_id).first()
        if target_id is not None
        else candidates.filter(
            change_kind=RegistrationCommandChangeKind.CREATED
        ).first()
    )
    if target is None:
        raise RegistrationSetupStateConflictError
    if target_kind == RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD:
        _require_profile_command_evidence(
            scope=scope,
            receipt=receipt,
            primary_target_id=target.target_id,
        )
    configuration_target = receipt.targets.filter(
        target_kind=RegistrationSetupCommandTarget.TargetKind.CONFIGURATION,
    ).first()
    return RegistrationDefinitionCommandResult(
        setup_id=receipt.setup_id,
        receipt_id=receipt.id,
        target_id=target.target_id,
        resulting_version=int(receipt.resulting_version),
        action=receipt.action,
        configuration_id=(
            scope.configuration.id if hasattr(scope, "configuration") else None
        ),
        configuration_content_digest=(
            configuration_target.content_digest if configuration_target else ""
        ),
        replayed=True,
    )


def _result(
    *,
    scope: Any,
    receipt: RegistrationSetupCommandReceipt,
    target_id: UUID,
    configuration_digest: str,
) -> RegistrationDefinitionCommandResult:
    return RegistrationDefinitionCommandResult(
        setup_id=scope.control.id,
        receipt_id=receipt.id,
        target_id=target_id,
        resulting_version=int(receipt.resulting_version),
        action=receipt.action,
        configuration_id=(
            scope.configuration.id if hasattr(scope, "configuration") else None
        ),
        configuration_content_digest=configuration_digest,
        replayed=False,
    )


def _target_digest(kind: str, value: Any, *, section_key: str | None = None) -> str:
    payload: dict[str, object] | None
    if kind == RegistrationSetupCommandTarget.TargetKind.QUESTION:
        payload = question_payload(value, section_key=section_key)
    elif kind == RegistrationSetupCommandTarget.TargetKind.PRODUCT:
        payload = product_payload(value, include_status=True)
    elif kind == RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY:
        payload = minor_policy_payload(value)
        if payload is None:
            raise RegistrationSetupStateConflictError
    elif kind == RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD:
        payload = profile_extension_payload(value)
    else:  # pragma: no cover - guarded by every caller's closed discriminator.
        raise RegistrationSetupStateConflictError
    return target_content_digest(kind=kind, payload=payload)


def _require_profile_command_evidence(  # noqa: PLR0912
    *,
    scope: _LockedProfileScope,
    receipt: RegistrationSetupCommandReceipt,
    primary_target_id: UUID,
) -> AuditEvent:
    """Prove exact profile targets and their canonical effect chain.

    Parameters
    ----------
    scope : _LockedProfileScope
        The exact tenant and resource scope of the operation.
    receipt : RegistrationSetupCommandReceipt
        The immutable command receipt proving the accepted transition.
    primary_target_id : UUID
        The primary target identifier within the requested scope.

    Returns
    -------
    AuditEvent
        The resolved AuditEvent for require profile command evidence.

    Raises
    ------
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    targets = tuple(
        receipt.targets.select_for_update().order_by(
            "target_kind",
            "target_id",
            "id",
        )
    )
    if not 1 <= len(targets) <= MAX_PROFILE_FIELDS + 1 or any(
        target.target_kind != RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD
        for target in targets
    ):
        raise RegistrationSetupStateConflictError

    action = receipt.action
    primary_change_kind_by_action: dict[str, str] = {
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_CREATED: (
            RegistrationCommandChangeKind.CREATED
        ),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_UPDATED: (
            RegistrationCommandChangeKind.UPDATED
        ),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_MOVED: (
            RegistrationCommandChangeKind.MOVED
        ),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED: (
            RegistrationCommandChangeKind.REVIEWED
        ),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_ACTIVATED: (
            RegistrationCommandChangeKind.ACTIVATED
        ),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_SUCCESSOR_STARTED: (
            RegistrationCommandChangeKind.CREATED
        ),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_RETIRED: (
            RegistrationCommandChangeKind.RETIRED
        ),
    }
    primary_change_kind = primary_change_kind_by_action.get(action)
    if primary_change_kind is None:
        raise RegistrationSetupStateConflictError
    primary_matches = tuple(
        target
        for target in targets
        if target.target_id == primary_target_id
        and target.change_kind == primary_change_kind
    )
    if len(primary_matches) != 1:
        raise RegistrationSetupStateConflictError

    allowed_secondary_by_action: dict[str, set[str]] = {
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_CREATED: {
            RegistrationCommandChangeKind.MOVED,
        },
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_UPDATED: set(),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_MOVED: {
            RegistrationCommandChangeKind.MOVED,
        },
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED: set(),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_ACTIVATED: {
            RegistrationCommandChangeKind.RETIRED,
        },
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_SUCCESSOR_STARTED: set(),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_RETIRED: {
            RegistrationCommandChangeKind.MOVED,
        },
    }
    secondary = tuple(target for target in targets if target != primary_matches[0])
    allowed_secondary = allowed_secondary_by_action[action]
    if any(target.change_kind not in allowed_secondary for target in secondary):
        raise RegistrationSetupStateConflictError
    if (
        action
        in {
            RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_UPDATED,
            RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED,
            RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_SUCCESSOR_STARTED,
        }
        and len(targets) != 1
    ):
        raise RegistrationSetupStateConflictError
    if action == RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_ACTIVATED and len(
        targets
    ) not in {1, MAX_PROFILE_ACTIVATION_TARGETS}:
        raise RegistrationSetupStateConflictError

    fields_by_id = {field.id: field for field in scope.fields}
    for target in targets:
        field = fields_by_id.get(target.target_id)
        if field is None or target.target_schema_version != field.version:
            raise RegistrationSetupStateConflictError
        has_later_target = RegistrationSetupCommandTarget.objects.filter(
            receipt__setup=scope.control,
            receipt__resulting_version__gt=receipt.resulting_version,
            target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
            target_id=target.target_id,
        ).exists()
        if not has_later_target and target.content_digest != _target_digest(
            RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
            field,
        ):
            raise RegistrationSetupStateConflictError

    expected_approval_time = None
    if action == RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED:
        has_later_review = RegistrationSetupCommandTarget.objects.filter(
            receipt__setup=scope.control,
            receipt__resulting_version__gt=receipt.resulting_version,
            receipt__action=(
                RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED
            ),
            target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
            target_id=primary_target_id,
            change_kind=RegistrationCommandChangeKind.REVIEWED,
        ).exists()
        if not has_later_review:
            expected_approval_time = fields_by_id[primary_target_id].approved_at
            if expected_approval_time is None:
                raise RegistrationSetupStateConflictError

    fixed_changed_fields: dict[str, tuple[str, ...]] = {
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_CREATED: (
            "profile_fields",
            "profile_field_order",
        ),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_MOVED: (
            "profile_field_order",
        ),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED: (
            "review_status",
            "approved_by",
            "approved_at",
        ),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_SUCCESSOR_STARTED: (
            "profile_fields",
            "supersedes",
        ),
        RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_RETIRED: (
            "status",
            "profile_field_order",
        ),
    }
    if action == RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_ACTIVATED:
        expected_changed_fields = (
            "status",
            *(
                ("superseded_status",)
                if len(targets) == MAX_PROFILE_ACTIVATION_TARGETS
                else ()
            ),
        )
    elif action == RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_UPDATED:
        audits = tuple(
            AuditEvent.objects.select_for_update().filter(
                organization_id=scope.organization.id,
                event_edition_id=scope.edition.id,
                correlation_id=receipt.correlation_id,
                operation="registration.setup.profile_field.changed",
                target_id=primary_target_id,
            )[:2]
        )
        allowed_fields = {
            "key",
            "label",
            "help_text",
            "field_type",
            "options",
            "purpose",
            "classification",
            "attendee_visible",
            "audience_policy",
            "audience_department_id",
            "writer_policy",
            "required",
            "review_status",
        }
        if (
            len(audits) != 1
            or not audits[0].changed_fields
            or any(field not in allowed_fields for field in audits[0].changed_fields)
        ):
            raise RegistrationSetupStateConflictError
        expected_changed_fields = tuple(audits[0].changed_fields)
    else:
        expected_changed_fields = fixed_changed_fields[action]

    return require_setup_command_evidence_graph(
        scope=scope,
        receipt=receipt,
        primary_target_id=primary_target_id,
        operation_segment="profile_field",
        expected_targets=tuple(target_expectation(target) for target in targets),
        expected_changed_fields=expected_changed_fields,
        expected_event_payload={
            "action": receipt.action,
            "configuration_version": "profile-extensions",
        },
        expected_occurred_at=expected_approval_time,
    )


def _delete_without_cascade(value: Any, *, dependency_error: type[Exception]) -> None:
    try:
        with transaction.atomic():
            deleted_count, _detail = value.delete()
    except (ProtectedError, RestrictedError) as error:
        raise dependency_error() from error
    except IntegrityError as error:
        if getattr(error.__cause__, "sqlstate", None) == "23503":
            raise dependency_error() from error
        raise
    if deleted_count != 1:
        raise dependency_error()


def _question_by_id(scope: Any, question_id: UUID) -> RegistrationQuestion:
    question = next((item for item in scope.questions if item.id == question_id), None)
    if question is None:
        raise RegistrationSetupQuestionUnavailableError
    return cast("RegistrationQuestion", question)


def _question_section(
    scope: Any,
    section_id: UUID | None,
) -> RegistrationSection | None:
    if section_id is None:
        return None
    section = next((item for item in scope.sections if item.id == section_id), None)
    if section is None:
        raise _field_error(
            "section_id",
            "Choose a section from this exact configuration.",
            "registration_setup_question_section_invalid",
        )
    return cast("RegistrationSection", section)


def _ordered_questions(
    *,
    questions: tuple[RegistrationQuestion, ...],
    question: RegistrationQuestion,
    after_question_id: UUID | None,
) -> tuple[RegistrationQuestion, ...]:
    remaining = [item for item in questions if item.id != question.id]
    if after_question_id == question.id:
        raise _field_error(
            "after_question_id",
            "Choose another question as the ordering anchor.",
            "registration_setup_question_move_invalid",
        )
    if after_question_id is None:
        insertion_index = 0
    else:
        anchor_index = next(
            (
                index
                for index, item in enumerate(remaining)
                if item.id == after_question_id
            ),
            None,
        )
        if anchor_index is None:
            raise RegistrationSetupQuestionUnavailableError
        insertion_index = anchor_index + 1
    remaining.insert(insertion_index, question)
    return tuple(remaining)


def _renumber_questions(
    questions: tuple[RegistrationQuestion, ...],
    *,
    resulting_version: int,
    changed_at: datetime,
) -> tuple[RegistrationQuestion, ...]:
    changed: list[RegistrationQuestion] = []
    for index, question in enumerate(questions, start=1):
        position = index * ORDER_POSITION_STEP
        if question.position == position:
            continue
        question.position = position
        question.last_changed_in_setup_version = resulting_version
        question.updated_at = changed_at
        if not question._state.adding:
            changed.append(question)
    return tuple(changed)


def _persist_questions(questions: tuple[RegistrationQuestion, ...]) -> None:
    if questions:
        RegistrationQuestion.objects.bulk_update(
            questions,
            fields=("position", "last_changed_in_setup_version", "updated_at"),
        )


def _condition_value_compatible(*, source: RegistrationQuestion, value: str) -> bool:
    return condition_value_is_compatible(
        field_type=source.field_type,
        options=source.options,
        value=value,
    )


def _validate_question_graph(questions: tuple[RegistrationQuestion, ...]) -> None:
    by_key = {
        question.key: (index, question) for index, question in enumerate(questions)
    }
    if len(by_key) != len(questions):
        raise _field_error(
            "key",
            "Question keys must be unique in this configuration.",
            "registration_setup_question_key_duplicate",
        )
    for index, question in enumerate(questions):
        source_key = question.condition_question_key
        condition_value = question.condition_value
        if bool(source_key) != bool(condition_value):
            raise _field_error(
                "condition_question_key",
                "A condition requires both its source question and value.",
                "registration_setup_question_condition_incomplete",
            )
        if not source_key:
            continue
        located = by_key.get(source_key)
        if located is None:
            raise _field_error(
                "condition_question_key",
                "Choose an existing question in this configuration.",
                "registration_setup_question_condition_source_missing",
            )
        source_index, source = located
        if source_index >= index:
            raise _field_error(
                "condition_question_key",
                "Conditional questions must follow their source question.",
                "registration_setup_question_condition_forward_reference",
            )
        if not _condition_value_compatible(source=source, value=condition_value):
            raise _field_error(
                "condition_value",
                "The condition value is incompatible with its source question.",
                "registration_setup_question_condition_value_invalid",
            )
        if (
            question.visibility == QuestionVisibility.ATTENDEE_AND_STAFF
            and source.visibility == QuestionVisibility.REGISTRATION_STAFF
        ):
            raise _field_error(
                "condition_question_key",
                "An attendee-visible question cannot depend on a staff-only answer.",
                "registration_setup_question_condition_hidden_source",
            )


def _question_values(
    *,
    key: object,
    label: object,
    help_text: object,
    field_type: object,
    required: object,
    options: object,
    purpose: object,
    visibility: object,
    classification: object,
    condition_question_key: object,
    condition_value: object,
) -> dict[str, object]:
    normalized_type = _closed_choice(
        field_type,
        field="field_type",
        choices=_QUESTION_TYPES,
    )
    normalized_options = _normalized_options(options)
    _validate_options_for_type(
        field_type=normalized_type,
        options=normalized_options,
    )
    normalized_condition_key = (
        _normalized_key(condition_question_key, field="condition_question_key")
        if condition_question_key
        else ""
    )
    normalized_condition_value = _normalized_optional_text(
        condition_value,
        field="condition_value",
        maximum=MAX_CONDITION_VALUE_LENGTH,
    )
    return {
        "key": _normalized_key(key, field="key"),
        "label": _normalized_required_text(
            label,
            field="label",
            maximum=MAX_QUESTION_LABEL_LENGTH,
        ),
        "help_text": _normalized_optional_text(
            help_text,
            field="help_text",
            maximum=MAX_QUESTION_HELP_LENGTH,
        ),
        "field_type": normalized_type,
        "required": _strict_boolean(required, field="required"),
        "options": normalized_options,
        "purpose": _normalized_required_text(
            purpose,
            field="purpose",
            maximum=MAX_QUESTION_PURPOSE_LENGTH,
        ),
        "visibility": _closed_choice(
            visibility,
            field="visibility",
            choices=_QUESTION_VISIBILITIES,
        ),
        "classification": _closed_choice(
            classification,
            field="classification",
            choices=_QUESTION_CLASSIFICATIONS,
        ),
        "condition_question_key": normalized_condition_key,
        "condition_value": normalized_condition_value,
    }


def _question_request_digest(
    *,
    action: str,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    question_id: UUID | None,
    values: dict[str, object],
    section_id: UUID | None,
    after_question_id: UUID | None,
    expected_version: int,
    reason: str,
) -> str:
    return canonical_digest(
        {
            "action": action,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "question_id": str(question_id) if question_id else None,
            "section_id": str(section_id) if section_id else None,
            "after_question_id": (
                str(after_question_id) if after_question_id else None
            ),
            **values,
            "expected_version": expected_version,
            "reason": reason,
        }
    )


def create_registration_question(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    key: str,
    label: str,
    help_text: str,
    field_type: str,
    required: bool,
    options: list[str],
    purpose: str,
    visibility: str,
    classification: str,
    condition_question_key: str,
    condition_value: str,
    section_id: UUID | None,
    after_question_id: UUID | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Create one typed question in a bounded, dependency-valid order.

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
    key : str
        The lookup, signing, or idempotency key selected by the contract.
    label : str
        The human-readable label shown to authorized readers.
    help_text : str
        The help text applied within the audited domain transition.
    field_type : str
        The closed field type discriminator defined by the domain catalog.
    required : bool
        The required applied within the audited domain transition.
    options : list[str]
        The configured option codes valid for the source question.
    purpose : str
        The documented purpose constraining collection and processing.
    visibility : str
        The closed disclosure audience applied to the projection.
    classification : str
        The closed sensitivity classification governing disclosure.
    condition_question_key : str
        The stable condition question key used to authenticate or deduplicate
        the operation.
    condition_value : str
        The condition value applied within the audited domain transition.
    section_id : UUID | None
        The section identifier within the requested scope.
    after_question_id : UUID | None
        The after question identifier within the requested scope.
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
    RegistrationDefinitionCommandResult
        The newly created RegistrationDefinitionCommandResult.

    Raises
    ------
    RegistrationSetupLimitExceededError
        If the operation encounters a registration setup limit exceeded
        condition.
    _field_error
        If the operation encounters a field error condition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    values = _question_values(
        key=key,
        label=label,
        help_text=help_text,
        field_type=field_type,
        required=required,
        options=options,
        purpose=purpose,
        visibility=visibility,
        classification=classification,
        condition_question_key=condition_question_key,
        condition_value=condition_value,
    )
    section_id = _strict_optional_uuid(section_id, field="section_id")
    after_question_id = _strict_optional_uuid(
        after_question_id,
        field="after_question_id",
    )
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.QUESTION_CREATED
    request_digest = _question_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        configuration_id=configuration_id,
        question_id=None,
        values=values,
        section_id=section_id,
        after_question_id=after_question_id,
        expected_version=expected_version,
        reason=normalized_reason,
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
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
                target_id=None,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        if len(scope.questions) >= MAX_SETUP_QUESTIONS:
            raise RegistrationSetupLimitExceededError
        if any(item.key == values["key"] for item in scope.questions):
            raise _field_error(
                "key",
                "This configuration already has that question key.",
                "registration_setup_question_key_duplicate",
            )
        section = _question_section(scope, section_id)
        resulting_version = current_version + 1
        question = RegistrationQuestion(
            configuration=scope.configuration,
            section=section,
            position=0,
            created_in_setup_version=resulting_version,
            last_changed_in_setup_version=resulting_version,
            **values,
        )
        ordered = _ordered_questions(
            questions=scope.questions,
            question=question,
            after_question_id=after_question_id,
        )
        changed = _renumber_questions(
            ordered,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        _validate_question_graph(ordered)
        question.full_clean()
        question.save(force_insert=True)
        _persist_questions(changed)
        configuration_digest = _advance_configuration(
            scope=scope,
            resulting_version=resulting_version,
            questions=ordered,
        )
        targets = (
            _TargetEvidence(
                target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
                target_id=question.id,
                change_kind=RegistrationCommandChangeKind.CREATED,
                content_digest=_target_digest(
                    RegistrationSetupCommandTarget.TargetKind.QUESTION,
                    question,
                    section_key=section.key if section else None,
                ),
            ),
            *(
                _TargetEvidence(
                    target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
                    target_id=moved.id,
                    change_kind=RegistrationCommandChangeKind.MOVED,
                    content_digest=_target_digest(
                        RegistrationSetupCommandTarget.TargetKind.QUESTION,
                        moved,
                        section_key=(moved.section.key if moved.section else None),
                    ),
                )
                for moved in changed
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=targets[0],
            targets=targets,
            configuration_digest=configuration_digest,
            changed_fields=("questions", "question_order"),
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
            target_id=question.id,
            configuration_digest=configuration_digest,
        )


def update_registration_question(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    question_id: UUID,
    key: str,
    label: str,
    help_text: str,
    field_type: str,
    required: bool,
    options: list[str],
    purpose: str,
    visibility: str,
    classification: str,
    condition_question_key: str,
    condition_value: str,
    section_id: UUID | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Completely replace one draft question's editable definition.

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
    question_id : UUID
        The question identifier within the requested scope.
    key : str
        The lookup, signing, or idempotency key selected by the contract.
    label : str
        The human-readable label shown to authorized readers.
    help_text : str
        The help text applied within the audited domain transition.
    field_type : str
        The closed field type discriminator defined by the domain catalog.
    required : bool
        The required applied within the audited domain transition.
    options : list[str]
        The configured option codes valid for the source question.
    purpose : str
        The documented purpose constraining collection and processing.
    visibility : str
        The closed disclosure audience applied to the projection.
    classification : str
        The closed sensitivity classification governing disclosure.
    condition_question_key : str
        The stable condition question key used to authenticate or deduplicate
        the operation.
    condition_value : str
        The condition value applied within the audited domain transition.
    section_id : UUID | None
        The section identifier within the requested scope.
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
    RegistrationDefinitionCommandResult
        The updated RegistrationDefinitionCommandResult after the transition is
        committed.

    Raises
    ------
    RegistrationSetupQuestionDependencyError
        If the operation encounters a registration setup question dependency
        condition.
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    _field_error
        If the operation encounters a field error condition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    question_id = _strict_uuid(question_id, field="question_id")
    values = _question_values(
        key=key,
        label=label,
        help_text=help_text,
        field_type=field_type,
        required=required,
        options=options,
        purpose=purpose,
        visibility=visibility,
        classification=classification,
        condition_question_key=condition_question_key,
        condition_value=condition_value,
    )
    section_id = _strict_optional_uuid(section_id, field="section_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.QUESTION_UPDATED
    request_digest = _question_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        configuration_id=configuration_id,
        question_id=question_id,
        values=values,
        section_id=section_id,
        after_question_id=None,
        expected_version=expected_version,
        reason=normalized_reason,
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
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
                target_id=question_id,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        question = _question_by_id(scope, question_id)
        section = _question_section(scope, section_id)
        if any(
            item.id != question.id and item.key == values["key"]
            for item in scope.questions
        ):
            raise _field_error(
                "key",
                "This configuration already has that question key.",
                "registration_setup_question_key_duplicate",
            )
        if question.key != values["key"] and any(
            item.condition_question_key == question.key for item in scope.questions
        ):
            raise RegistrationSetupQuestionDependencyError
        changed_fields = tuple(
            field
            for field, changed in (
                *(
                    (name, getattr(question, name) != value)
                    for name, value in values.items()
                ),
                ("section", question.section_id != section_id),
            )
            if changed
        )
        if not changed_fields:
            raise RegistrationSetupStateConflictError
        resulting_version = current_version + 1
        for name, value in values.items():
            setattr(question, name, value)
        question.section = section
        question.last_changed_in_setup_version = resulting_version
        _validate_question_graph(scope.questions)
        question.save(
            update_fields=(
                *values.keys(),
                "section",
                "last_changed_in_setup_version",
                "updated_at",
            )
        )
        configuration_digest = _advance_configuration(
            scope=scope,
            resulting_version=resulting_version,
            questions=scope.questions,
        )
        target = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
            target_id=question.id,
            change_kind=RegistrationCommandChangeKind.UPDATED,
            content_digest=_target_digest(
                RegistrationSetupCommandTarget.TargetKind.QUESTION,
                question,
                section_key=section.key if section else None,
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=target,
            targets=(target,),
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
            target_id=question.id,
            configuration_digest=configuration_digest,
        )


def _question_order_request_digest(
    *,
    action: str,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    question_id: UUID,
    after_question_id: UUID | None,
    expected_version: int,
    reason: str,
) -> str:
    return canonical_digest(
        {
            "action": action,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "question_id": str(question_id),
            "after_question_id": (
                str(after_question_id) if after_question_id else None
            ),
            "expected_version": expected_version,
            "reason": reason,
        }
    )


def move_registration_question(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    question_id: UUID,
    after_question_id: UUID | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Move registration question.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    configuration_id : UUID
        The identifier of the configuration.
    question_id : UUID
        The identifier of the question.
    after_question_id : UUID | None
        The identifier of the after question.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The registration definition command result.

    Raises
    ------
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    question_id = _strict_uuid(question_id, field="question_id")
    after_question_id = _strict_optional_uuid(
        after_question_id,
        field="after_question_id",
    )
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.QUESTION_MOVED
    request_digest = _question_order_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        configuration_id=configuration_id,
        question_id=question_id,
        after_question_id=after_question_id,
        expected_version=expected_version,
        reason=normalized_reason,
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
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
                target_id=question_id,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        question = _question_by_id(scope, question_id)
        ordered = _ordered_questions(
            questions=scope.questions,
            question=question,
            after_question_id=after_question_id,
        )
        if tuple(item.id for item in ordered) == tuple(
            item.id for item in scope.questions
        ):
            raise RegistrationSetupStateConflictError
        _validate_question_graph(ordered)
        resulting_version = current_version + 1
        changed = _renumber_questions(
            ordered,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        if all(item.id != question.id for item in changed):
            question.last_changed_in_setup_version = resulting_version
            question.updated_at = scope.evaluated_at
            changed = (*changed, question)
        _persist_questions(changed)
        configuration_digest = _advance_configuration(
            scope=scope,
            resulting_version=resulting_version,
            questions=ordered,
        )
        section_keys = {section.id: section.key for section in scope.sections}
        targets = tuple(
            _TargetEvidence(
                target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
                target_id=moved.id,
                change_kind=RegistrationCommandChangeKind.MOVED,
                content_digest=_target_digest(
                    RegistrationSetupCommandTarget.TargetKind.QUESTION,
                    moved,
                    section_key=(
                        section_keys.get(moved.section_id)
                        if moved.section_id is not None
                        else None
                    ),
                ),
            )
            for moved in changed
        )
        primary = next(item for item in targets if item.target_id == question.id)
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=primary,
            targets=targets,
            configuration_digest=configuration_digest,
            changed_fields=("question_order",),
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
            target_id=question.id,
            configuration_digest=configuration_digest,
        )


def delete_registration_question(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    question_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Delete registration question.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    configuration_id : UUID
        The identifier of the configuration.
    question_id : UUID
        The identifier of the question.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The registration definition command result.

    Raises
    ------
    RegistrationSetupQuestionDependencyError
        If the operation encounters a registration setup question dependency
        condition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    question_id = _strict_uuid(question_id, field="question_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.QUESTION_DELETED
    request_digest = _question_order_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        configuration_id=configuration_id,
        question_id=question_id,
        after_question_id=None,
        expected_version=expected_version,
        reason=normalized_reason,
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
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
                target_id=question_id,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        question = _question_by_id(scope, question_id)
        if (
            RegistrationSubmission.objects.select_for_update()
            .filter(
                registration__configuration_id=scope.configuration.id,
                organization_id=scope.organization.id,
                edition_id=scope.edition.id,
            )
            .exists()
        ):
            raise RegistrationSetupQuestionDependencyError
        if any(
            item.condition_question_key == question.key
            for item in scope.questions
            if item.id != question.id
        ):
            raise RegistrationSetupQuestionDependencyError
        resulting_version = current_version + 1
        section_key = next(
            (
                section.key
                for section in scope.sections
                if section.id == question.section_id
            ),
            None,
        )
        deleted_digest = _target_digest(
            RegistrationSetupCommandTarget.TargetKind.QUESTION,
            question,
            section_key=section_key,
        )
        remaining = tuple(item for item in scope.questions if item.id != question.id)
        _delete_without_cascade(
            question,
            dependency_error=RegistrationSetupQuestionDependencyError,
        )
        changed = _renumber_questions(
            remaining,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        _persist_questions(changed)
        configuration_digest = _advance_configuration(
            scope=scope,
            resulting_version=resulting_version,
            questions=remaining,
        )
        section_keys = {section.id: section.key for section in scope.sections}
        primary = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
            target_id=question_id,
            change_kind=RegistrationCommandChangeKind.DELETED,
            content_digest=deleted_digest,
        )
        targets = (
            primary,
            *(
                _TargetEvidence(
                    target_kind=RegistrationSetupCommandTarget.TargetKind.QUESTION,
                    target_id=moved.id,
                    change_kind=RegistrationCommandChangeKind.MOVED,
                    content_digest=_target_digest(
                        RegistrationSetupCommandTarget.TargetKind.QUESTION,
                        moved,
                        section_key=(
                            section_keys.get(moved.section_id)
                            if moved.section_id is not None
                            else None
                        ),
                    ),
                )
                for moved in changed
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=primary,
            targets=targets,
            configuration_digest=configuration_digest,
            changed_fields=("questions", "question_order"),
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
            target_id=question_id,
            configuration_digest=configuration_digest,
        )


def _product_by_id(scope: Any, product_id: UUID) -> AdmissionProduct:
    product = next((item for item in scope.products if item.id == product_id), None)
    if product is None:
        raise RegistrationSetupProductUnavailableError
    return cast("AdmissionProduct", product)


def _normalized_capacity_codes(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_PRODUCT_CAPACITY_CODES:
        raise _field_error(
            "required_capacity_codes",
            "Choose at most 32 capacity codes.",
            "registration_setup_product_capacity_codes_invalid",
        )
    codes: list[str] = []
    for candidate in value:
        if not isinstance(candidate, str):
            raise _field_error(
                "required_capacity_codes",
                "Choose documented capacity codes.",
                "registration_setup_product_capacity_codes_invalid",
            )
        code = unicodedata.normalize("NFC", candidate).strip().lower()
        if (
            not code
            or len(code) > MAX_PRODUCT_CODE_LENGTH
            or re.fullmatch(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*", code) is None
        ):
            raise _field_error(
                "required_capacity_codes",
                "Capacity codes must use their stable lowercase catalog value.",
                "registration_setup_product_capacity_codes_invalid",
            )
        codes.append(code)
    if len(set(codes)) != len(codes):
        raise _field_error(
            "required_capacity_codes",
            "Capacity codes must be unique.",
            "registration_setup_product_capacity_codes_duplicate",
        )
    return codes


def _product_values(
    *,
    code: object,
    name: object,
    description: object,
    price_minor: object,
    capacity: object,
    capacity_ceiling: object,
    entitlement_code: object,
    entitlement_name: object,
    sales_open_at: object,
    sales_close_at: object,
    required_capacity_codes: object,
    eligibility_explanation: object,
    waitlist_enabled: object,
    payment_window_minutes: object,
) -> dict[str, object]:
    normalized_capacity = cast(
        "int",
        _strict_integer(
            capacity,
            field="capacity",
            minimum=1,
            maximum=MAX_SETUP_CAPACITY,
        ),
    )
    normalized_ceiling = _strict_integer(
        capacity_ceiling,
        field="capacity_ceiling",
        minimum=1,
        maximum=MAX_SETUP_CAPACITY,
        optional=True,
    )
    if normalized_ceiling is not None and normalized_ceiling < normalized_capacity:
        raise _field_error(
            "capacity_ceiling",
            "The hard ceiling cannot be below the initial capacity.",
            "registration_setup_product_capacity_ceiling_invalid",
        )
    open_at = _aware_datetime(sales_open_at, field="sales_open_at")
    close_at = _aware_datetime(sales_close_at, field="sales_close_at")
    if bool(open_at) != bool(close_at) or (
        open_at is not None and close_at is not None and close_at <= open_at
    ):
        raise _field_error(
            "sales_close_at",
            "Provide both product sale times, with closing later than opening.",
            "registration_setup_product_sales_window_invalid",
        )
    codes = _normalized_capacity_codes(required_capacity_codes)
    explanation = _normalized_optional_text(
        eligibility_explanation,
        field="eligibility_explanation",
        maximum=MAX_PRODUCT_ELIGIBILITY_LENGTH,
    )
    if codes and not explanation:
        raise _field_error(
            "eligibility_explanation",
            "Explain attendee eligibility for a restricted product.",
            "registration_setup_product_eligibility_explanation_required",
        )
    return {
        "code": _normalized_key(code, field="code"),
        "name": _normalized_required_text(
            name,
            field="name",
            maximum=MAX_PRODUCT_NAME_LENGTH,
        ),
        "description": _normalized_optional_text(
            description,
            field="description",
            maximum=MAX_PRODUCT_DESCRIPTION_LENGTH,
        ),
        "price_minor": _strict_integer(
            price_minor,
            field="price_minor",
            minimum=0,
            maximum=MAX_PRODUCT_PRICE_MINOR,
        ),
        "capacity": normalized_capacity,
        "capacity_ceiling": normalized_ceiling,
        "entitlement_code": _normalized_key(
            entitlement_code,
            field="entitlement_code",
        ),
        "entitlement_name": _normalized_required_text(
            entitlement_name,
            field="entitlement_name",
            maximum=MAX_PRODUCT_NAME_LENGTH,
        ),
        "sales_open_at": open_at,
        "sales_close_at": close_at,
        "required_capacity_codes": codes,
        "eligibility_explanation": explanation,
        "waitlist_enabled": _strict_boolean(
            waitlist_enabled,
            field="waitlist_enabled",
        ),
        "payment_window_minutes": _strict_integer(
            payment_window_minutes,
            field="payment_window_minutes",
            minimum=MIN_PAYMENT_WINDOW_MINUTES,
            maximum=MAX_PAYMENT_WINDOW_MINUTES,
            optional=True,
        ),
    }


def _validate_product_scope(scope: Any, values: dict[str, object]) -> None:
    if values["waitlist_enabled"] and not scope.configuration.waitlist_enabled:
        raise _field_error(
            "waitlist_enabled",
            "A product cannot enable waiting when the registration wait-list is off.",
            "registration_setup_product_waitlist_parent_disabled",
        )
    codes = cast("list[str]", values["required_capacity_codes"])
    if not codes:
        return
    available = {
        code
        for code in codes
        if ParticipationCapacity.objects.select_for_update()
        .filter(
            participation__organization_id=scope.organization.id,
            participation__edition_id=scope.edition.id,
            status=ParticipationCapacity.Status.ACTIVE,
            code=code,
        )
        .order_by("id")
        .exists()
    }
    if available != set(codes):
        raise _field_error(
            "required_capacity_codes",
            "Every restriction must use an active capacity in this edition.",
            "registration_setup_product_capacity_code_unavailable",
        )


def _ordered_products(
    *,
    products: tuple[AdmissionProduct, ...],
    product: AdmissionProduct,
    after_product_id: UUID | None,
) -> tuple[AdmissionProduct, ...]:
    remaining = [item for item in products if item.id != product.id]
    if after_product_id == product.id:
        raise _field_error(
            "after_product_id",
            "Choose another product as the ordering anchor.",
            "registration_setup_product_move_invalid",
        )
    if after_product_id is None:
        index = 0
    else:
        anchor = next(
            (i for i, item in enumerate(remaining) if item.id == after_product_id),
            None,
        )
        if anchor is None:
            raise RegistrationSetupProductUnavailableError
        index = anchor + 1
    remaining.insert(index, product)
    return tuple(remaining)


def _renumber_products(
    products: tuple[AdmissionProduct, ...],
    *,
    resulting_version: int,
    changed_at: datetime,
) -> tuple[AdmissionProduct, ...]:
    changed: list[AdmissionProduct] = []
    for index, product in enumerate(products, start=1):
        position = index * ORDER_POSITION_STEP
        if product.position == position:
            continue
        product.position = position
        product.last_changed_in_setup_version = resulting_version
        product.updated_at = changed_at
        if not product._state.adding:
            changed.append(product)
    return tuple(changed)


def _persist_products(products: tuple[AdmissionProduct, ...]) -> None:
    if products:
        AdmissionProduct.objects.bulk_update(
            products,
            fields=("position", "last_changed_in_setup_version", "updated_at"),
        )


def _product_request_digest(
    *,
    action: str,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    product_id: UUID | None,
    values: dict[str, object],
    after_product_id: UUID | None,
    expected_version: int,
    reason: str,
) -> str:
    return canonical_digest(
        {
            "action": action,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "product_id": str(product_id) if product_id else None,
            "after_product_id": str(after_product_id) if after_product_id else None,
            **values,
            "expected_version": expected_version,
            "reason": reason,
        }
    )


def create_admission_product(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    code: str,
    name: str,
    description: str,
    price_minor: int,
    capacity: int,
    capacity_ceiling: int | None = None,
    entitlement_code: str,
    entitlement_name: str,
    sales_open_at: datetime | None,
    sales_close_at: datetime | None,
    required_capacity_codes: list[str],
    eligibility_explanation: str,
    waitlist_enabled: bool,
    payment_window_minutes: int | None,
    after_product_id: UUID | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Create admission product.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    configuration_id : UUID
        The identifier of the configuration.
    code : str
        The stable machine-readable code.
    name : str
        The human-readable name.
    description : str
        The human-readable description.
    price_minor : int
        The price in minor currency units.
    capacity : int
        The capacity applied by the operation.
    capacity_ceiling : int | None, default=None
        The hard upper capacity bound.
    entitlement_code : str
        The stable entitlement code from the relevant closed catalog.
    entitlement_name : str
        The human-readable entitlement name shown to authorized readers.
    sales_open_at : datetime | None
        The timezone-aware timestamp for sales open.
    sales_close_at : datetime | None
        The timezone-aware timestamp for sales close.
    required_capacity_codes : list[str]
        The required capacity codes applied within the audited domain transition.
    eligibility_explanation : str
        The bounded eligibility explanation retained for authorized readers.
    waitlist_enabled : bool
        Whether wait-list enrollment is enabled.
    payment_window_minutes : int | None
        The payment window minutes applied within the audited domain transition.
    after_product_id : UUID | None
        The identifier of the after product.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    RegistrationSetupLimitExceededError
        If the operation encounters a registration setup limit exceeded
        condition.
    _field_error
        If the operation encounters a field error condition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    values = _product_values(
        code=code,
        name=name,
        description=description,
        price_minor=price_minor,
        capacity=capacity,
        capacity_ceiling=capacity_ceiling,
        entitlement_code=entitlement_code,
        entitlement_name=entitlement_name,
        sales_open_at=sales_open_at,
        sales_close_at=sales_close_at,
        required_capacity_codes=required_capacity_codes,
        eligibility_explanation=eligibility_explanation,
        waitlist_enabled=waitlist_enabled,
        payment_window_minutes=payment_window_minutes,
    )
    if values["capacity_ceiling"] is None:
        values["capacity_ceiling"] = values["capacity"]
    after_product_id = _strict_optional_uuid(
        after_product_id,
        field="after_product_id",
    )
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PRODUCT_CREATED
    request_digest = _product_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        configuration_id=configuration_id,
        product_id=None,
        values=values,
        after_product_id=after_product_id,
        expected_version=expected_version,
        reason=normalized_reason,
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
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                target_id=None,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        if len(scope.products) >= MAX_SETUP_PRODUCTS:
            raise RegistrationSetupLimitExceededError
        if any(item.code == values["code"] for item in scope.products):
            raise _field_error(
                "code",
                "This configuration already has that product code.",
                "registration_setup_product_code_duplicate",
            )
        _validate_product_scope(scope, values)
        resulting_version = current_version + 1
        product = AdmissionProduct(
            configuration=scope.configuration,
            status=AdmissionProduct.Status.AVAILABLE,
            position=0,
            created_in_setup_version=resulting_version,
            last_changed_in_setup_version=resulting_version,
            **values,
        )
        ordered = _ordered_products(
            products=scope.products,
            product=product,
            after_product_id=after_product_id,
        )
        changed = _renumber_products(
            ordered,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        product.full_clean()
        product.save(force_insert=True)
        _persist_products(changed)
        configuration_digest = _advance_configuration(
            scope=scope,
            resulting_version=resulting_version,
            products=ordered,
        )
        targets = (
            _TargetEvidence(
                target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                target_id=product.id,
                change_kind=RegistrationCommandChangeKind.CREATED,
                content_digest=_target_digest(
                    RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                    product,
                ),
            ),
            *(
                _TargetEvidence(
                    target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                    target_id=moved.id,
                    change_kind=RegistrationCommandChangeKind.MOVED,
                    content_digest=_target_digest(
                        RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                        moved,
                    ),
                )
                for moved in changed
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=targets[0],
            targets=targets,
            configuration_digest=configuration_digest,
            changed_fields=("products", "product_order"),
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
            target_id=product.id,
            configuration_digest=configuration_digest,
        )


def update_admission_product(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    product_id: UUID,
    code: str,
    name: str,
    description: str,
    price_minor: int,
    capacity: int,
    capacity_ceiling: int | None = None,
    entitlement_code: str,
    entitlement_name: str,
    sales_open_at: datetime | None,
    sales_close_at: datetime | None,
    required_capacity_codes: list[str],
    eligibility_explanation: str,
    waitlist_enabled: bool,
    payment_window_minutes: int | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Update admission product.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    configuration_id : UUID
        The identifier of the configuration.
    product_id : UUID
        The identifier of the product.
    code : str
        The stable machine-readable code.
    name : str
        The human-readable name.
    description : str
        The human-readable description.
    price_minor : int
        The price in minor currency units.
    capacity : int
        The capacity applied by the operation.
    capacity_ceiling : int | None, default=None
        The hard upper capacity bound.
    entitlement_code : str
        The stable entitlement code from the relevant closed catalog.
    entitlement_name : str
        The human-readable entitlement name shown to authorized readers.
    sales_open_at : datetime | None
        The timezone-aware timestamp for sales open.
    sales_close_at : datetime | None
        The timezone-aware timestamp for sales close.
    required_capacity_codes : list[str]
        The required capacity codes applied within the audited domain transition.
    eligibility_explanation : str
        The bounded eligibility explanation retained for authorized readers.
    waitlist_enabled : bool
        Whether wait-list enrollment is enabled.
    payment_window_minutes : int | None
        The payment window minutes applied within the audited domain transition.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    _field_error
        If the operation encounters a field error condition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    product_id = _strict_uuid(product_id, field="product_id")
    values = _product_values(
        code=code,
        name=name,
        description=description,
        price_minor=price_minor,
        capacity=capacity,
        capacity_ceiling=capacity_ceiling,
        entitlement_code=entitlement_code,
        entitlement_name=entitlement_name,
        sales_open_at=sales_open_at,
        sales_close_at=sales_close_at,
        required_capacity_codes=required_capacity_codes,
        eligibility_explanation=eligibility_explanation,
        waitlist_enabled=waitlist_enabled,
        payment_window_minutes=payment_window_minutes,
    )
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PRODUCT_UPDATED
    request_digest = _product_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        configuration_id=configuration_id,
        product_id=product_id,
        values=values,
        after_product_id=None,
        expected_version=expected_version,
        reason=normalized_reason,
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
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                target_id=product_id,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        product = _product_by_id(scope, product_id)
        if values["capacity_ceiling"] is None:
            values["capacity_ceiling"] = product.capacity_ceiling
        if any(
            item.id != product.id and item.code == values["code"]
            for item in scope.products
        ):
            raise _field_error(
                "code",
                "This configuration already has that product code.",
                "registration_setup_product_code_duplicate",
            )
        _validate_product_scope(scope, values)
        changed_fields = tuple(
            name for name, value in values.items() if getattr(product, name) != value
        )
        if not changed_fields:
            raise RegistrationSetupStateConflictError
        resulting_version = current_version + 1
        for attribute_name, value in values.items():
            setattr(product, attribute_name, value)
        product.last_changed_in_setup_version = resulting_version
        product.save(
            update_fields=(
                *values.keys(),
                "last_changed_in_setup_version",
                "updated_at",
            )
        )
        configuration_digest = _advance_configuration(
            scope=scope,
            resulting_version=resulting_version,
            products=scope.products,
        )
        target = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
            target_id=product.id,
            change_kind=RegistrationCommandChangeKind.UPDATED,
            content_digest=_target_digest(
                RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                product,
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=target,
            targets=(target,),
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
            target_id=product.id,
            configuration_digest=configuration_digest,
        )


def _product_order_digest(
    *,
    action: str,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    product_id: UUID,
    after_product_id: UUID | None,
    expected_version: int,
    reason: str,
) -> str:
    return canonical_digest(
        {
            "action": action,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "product_id": str(product_id),
            "after_product_id": str(after_product_id) if after_product_id else None,
            "expected_version": expected_version,
            "reason": reason,
        }
    )


def move_admission_product(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    product_id: UUID,
    after_product_id: UUID | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Move admission product.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    configuration_id : UUID
        The identifier of the configuration.
    product_id : UUID
        The identifier of the product.
    after_product_id : UUID | None
        The identifier of the after product.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The registration definition command result.

    Raises
    ------
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    product_id = _strict_uuid(product_id, field="product_id")
    after_product_id = _strict_optional_uuid(
        after_product_id,
        field="after_product_id",
    )
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PRODUCT_MOVED
    request_digest = _product_order_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        configuration_id=configuration_id,
        product_id=product_id,
        after_product_id=after_product_id,
        expected_version=expected_version,
        reason=normalized_reason,
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
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                target_id=product_id,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        product = _product_by_id(scope, product_id)
        ordered = _ordered_products(
            products=scope.products,
            product=product,
            after_product_id=after_product_id,
        )
        if tuple(item.id for item in ordered) == tuple(
            item.id for item in scope.products
        ):
            raise RegistrationSetupStateConflictError
        resulting_version = current_version + 1
        changed = _renumber_products(
            ordered,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        if all(item.id != product.id for item in changed):
            product.last_changed_in_setup_version = resulting_version
            product.updated_at = scope.evaluated_at
            changed = (*changed, product)
        _persist_products(changed)
        configuration_digest = _advance_configuration(
            scope=scope,
            resulting_version=resulting_version,
            products=ordered,
        )
        targets = tuple(
            _TargetEvidence(
                target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                target_id=moved.id,
                change_kind=RegistrationCommandChangeKind.MOVED,
                content_digest=_target_digest(
                    RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                    moved,
                ),
            )
            for moved in changed
        )
        primary = next(item for item in targets if item.target_id == product.id)
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=primary,
            targets=targets,
            configuration_digest=configuration_digest,
            changed_fields=("product_order",),
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
            target_id=product.id,
            configuration_digest=configuration_digest,
        )


def delete_admission_product(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    product_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Delete admission product.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    configuration_id : UUID
        The identifier of the configuration.
    product_id : UUID
        The identifier of the product.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The registration definition command result.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    product_id = _strict_uuid(product_id, field="product_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PRODUCT_DELETED
    request_digest = _product_order_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        configuration_id=configuration_id,
        product_id=product_id,
        after_product_id=None,
        expected_version=expected_version,
        reason=normalized_reason,
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
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                target_id=product_id,
            )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        product = _product_by_id(scope, product_id)
        resulting_version = current_version + 1
        deleted_digest = _target_digest(
            RegistrationSetupCommandTarget.TargetKind.PRODUCT,
            product,
        )
        remaining = tuple(item for item in scope.products if item.id != product.id)
        _delete_without_cascade(
            product,
            dependency_error=RegistrationSetupProductDependencyError,
        )
        changed = _renumber_products(
            remaining,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        _persist_products(changed)
        configuration_digest = _advance_configuration(
            scope=scope,
            resulting_version=resulting_version,
            products=remaining,
        )
        primary = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
            target_id=product_id,
            change_kind=RegistrationCommandChangeKind.DELETED,
            content_digest=deleted_digest,
        )
        targets = (
            primary,
            *(
                _TargetEvidence(
                    target_kind=RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                    target_id=moved.id,
                    change_kind=RegistrationCommandChangeKind.MOVED,
                    content_digest=_target_digest(
                        RegistrationSetupCommandTarget.TargetKind.PRODUCT,
                        moved,
                    ),
                )
                for moved in changed
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=primary,
            targets=targets,
            configuration_digest=configuration_digest,
            changed_fields=("products", "product_order"),
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
            target_id=product_id,
            configuration_digest=configuration_digest,
        )


def _minor_values(
    *,
    enabled: object,
    minor_age_threshold: object,
    guardian_notice_version: object,
    jurisdiction_code: object,
    review_reference: object,
) -> dict[str, object]:
    is_enabled = _strict_boolean(enabled, field="enabled")
    values: dict[str, object] = {
        "enabled": is_enabled,
        "minor_age_threshold": _strict_integer(
            minor_age_threshold,
            field="minor_age_threshold",
            minimum=1,
            maximum=120,
        ),
        "guardian_notice_version": _normalized_optional_text(
            guardian_notice_version,
            field="guardian_notice_version",
            maximum=MAX_MINOR_NOTICE_VERSION_LENGTH,
        ),
        "jurisdiction_code": _normalized_optional_text(
            jurisdiction_code,
            field="jurisdiction_code",
            maximum=MAX_MINOR_JURISDICTION_LENGTH,
        ),
        "review_reference": _normalized_optional_text(
            review_reference,
            field="review_reference",
            maximum=MAX_MINOR_REVIEW_REFERENCE_LENGTH,
        ),
    }
    if is_enabled:
        for field in (
            "guardian_notice_version",
            "jurisdiction_code",
            "review_reference",
        ):
            if not values[field]:
                raise _field_error(
                    field,
                    "Enabled minor registration requires reviewed evidence.",
                    "registration_setup_minor_policy_review_required",
                )
    return values


def _minor_request_digest(
    *,
    action: str,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    policy_id: UUID | None,
    values: dict[str, object],
    expected_version: int,
    reason: str,
) -> str:
    return canonical_digest(
        {
            "action": action,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "configuration_id": str(configuration_id),
            "policy_id": str(policy_id) if policy_id else None,
            **values,
            "expected_version": expected_version,
            "reason": reason,
        }
    )


def _minor_policy_receipt_target(
    *,
    receipt: RegistrationSetupCommandReceipt,
    change_kinds: frozenset[str],
) -> RegistrationSetupCommandTarget:
    targets = tuple(
        receipt.targets.filter(
            target_kind=RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
            change_kind__in=change_kinds,
        )[:2]
    )
    if len(targets) != 1:
        raise RegistrationSetupStateConflictError
    return targets[0]


def _replay_minor_policy_set(
    *,
    scope: Any,
    receipt: RegistrationSetupCommandReceipt,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    values: dict[str, object],
    expected_version: int,
    reason: str,
) -> RegistrationDefinitionCommandResult:
    allowed_actions: dict[str, str] = {
        RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED: (
            RegistrationCommandChangeKind.CREATED
        ),
        RegistrationSetupCommandReceipt.Action.MINOR_POLICY_UPDATED: (
            RegistrationCommandChangeKind.UPDATED
        ),
    }
    change_kind = allowed_actions.get(receipt.action)
    if change_kind is None:
        raise RegistrationSetupRetryConflictError
    target = _minor_policy_receipt_target(
        receipt=receipt,
        change_kinds=frozenset({change_kind}),
    )
    request_digest = _minor_request_digest(
        action=receipt.action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        configuration_id=configuration_id,
        policy_id=(
            None
            if receipt.action
            == RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED
            else target.target_id
        ),
        values=values,
        expected_version=expected_version,
        reason=reason,
    )
    return _result_from_receipt(
        scope=scope,
        receipt=receipt,
        action=receipt.action,
        request_digest=request_digest,
        target_kind=RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
        target_id=target.target_id,
    )


def _replay_minor_policy_remove(
    *,
    scope: Any,
    receipt: RegistrationSetupCommandReceipt,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    expected_version: int,
    reason: str,
) -> RegistrationDefinitionCommandResult:
    action = RegistrationSetupCommandReceipt.Action.MINOR_POLICY_REMOVED
    if receipt.action != action:
        raise RegistrationSetupRetryConflictError
    target = _minor_policy_receipt_target(
        receipt=receipt,
        change_kinds=frozenset({RegistrationCommandChangeKind.DELETED}),
    )
    request_digest = _minor_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        configuration_id=configuration_id,
        policy_id=target.target_id,
        values={},
        expected_version=expected_version,
        reason=reason,
    )
    return _result_from_receipt(
        scope=scope,
        receipt=receipt,
        action=action,
        request_digest=request_digest,
        target_kind=RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
        target_id=target.target_id,
    )


def set_minor_registration_policy(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    enabled: bool,
    minor_age_threshold: int,
    guardian_notice_version: str,
    jurisdiction_code: str,
    review_reference: str,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Create or completely update the configuration's one minor policy.

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
    enabled : bool
        The enabled applied within the audited domain transition.
    minor_age_threshold : int
        The minor age threshold applied within the audited domain transition.
    guardian_notice_version : str
        The expected guardian notice version used to reject stale updates.
    jurisdiction_code : str
        The stable jurisdiction code from the relevant closed catalog.
    review_reference : str
        The provider or source review reference retained for reconciliation.
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
    RegistrationDefinitionCommandResult
        The updated RegistrationDefinitionCommandResult after the transition is
        committed.

    Raises
    ------
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    _field_error
        If the operation encounters a field error condition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    values = _minor_values(
        enabled=enabled,
        minor_age_threshold=minor_age_threshold,
        guardian_notice_version=guardian_notice_version,
        jurisdiction_code=jurisdiction_code,
        review_reference=review_reference,
    )
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
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
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _replay_minor_policy_set(
                scope=scope,
                receipt=replay,
                actor=actor,
                organization_id=organization_id,
                series_id=series_id,
                edition_id=edition_id,
                configuration_id=configuration_id,
                values=values,
                expected_version=expected_version,
                reason=normalized_reason,
            )
        existing = scope.minor_policy
        action = (
            RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED
            if existing is None
            else RegistrationSetupCommandReceipt.Action.MINOR_POLICY_UPDATED
        )
        request_digest = _minor_request_digest(
            action=action,
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            configuration_id=configuration_id,
            policy_id=existing.id if existing else None,
            values=values,
            expected_version=expected_version,
            reason=normalized_reason,
        )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        if (
            cast("int", values["minor_age_threshold"])
            <= scope.configuration.minimum_age
        ):
            raise _field_error(
                "minor_age_threshold",
                "The guardian threshold must exceed the absolute minimum age.",
                "registration_setup_minor_policy_age_band_invalid",
            )
        changed_fields = tuple(
            values.keys()
            if existing is None
            else (
                name
                for name, value in values.items()
                if getattr(existing, name) != value
            )
        )
        if existing is not None and not changed_fields:
            raise RegistrationSetupStateConflictError
        resulting_version = current_version + 1
        if existing is None:
            policy = MinorRegistrationPolicy(
                configuration=scope.configuration,
                reviewed_by=scope.actor,
                reviewed_at=scope.evaluated_at,
                created_in_setup_version=resulting_version,
                last_changed_in_setup_version=resulting_version,
                **values,
            )
            policy.full_clean()
            policy.save(force_insert=True)
            change_kind = RegistrationCommandChangeKind.CREATED
        else:
            policy = existing
            for name, value in values.items():
                setattr(policy, name, value)
            policy.reviewed_by = scope.actor
            policy.reviewed_at = scope.evaluated_at
            policy.last_changed_in_setup_version = resulting_version
            policy.full_clean()
            policy.save(
                update_fields=(
                    *values.keys(),
                    "reviewed_by",
                    "reviewed_at",
                    "last_changed_in_setup_version",
                    "updated_at",
                )
            )
            change_kind = RegistrationCommandChangeKind.UPDATED
        configuration_digest = _advance_configuration(
            scope=scope,
            resulting_version=resulting_version,
            minor_policy=policy,
        )
        target = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
            target_id=policy.id,
            change_kind=change_kind,
            content_digest=_target_digest(
                RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
                policy,
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=target,
            targets=(target,),
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
            target_id=policy.id,
            configuration_digest=configuration_digest,
        )


def remove_minor_registration_policy(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Remove minor registration policy.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    configuration_id : UUID
        The identifier of the configuration.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The registration definition command result.

    Raises
    ------
    RegistrationSetupMinorPolicyUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    configuration_id = _strict_uuid(configuration_id, field="configuration_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.MINOR_POLICY_REMOVED
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
            return _replay_minor_policy_remove(
                scope=scope,
                receipt=replay,
                actor=actor,
                organization_id=organization_id,
                series_id=series_id,
                edition_id=edition_id,
                configuration_id=configuration_id,
                expected_version=expected_version,
                reason=normalized_reason,
            )
        policy = scope.minor_policy
        request_digest = _minor_request_digest(
            action=action,
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            configuration_id=configuration_id,
            policy_id=policy.id if policy else None,
            values={},
            expected_version=expected_version,
            reason=normalized_reason,
        )
        _require_editable_draft(scope)
        current_version = _require_current_version(scope, expected_version)
        _require_current_digest(scope)
        if policy is None:
            raise RegistrationSetupMinorPolicyUnavailableError
        resulting_version = current_version + 1
        deleted_digest = _target_digest(
            RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
            policy,
        )
        policy_id = policy.id
        _delete_without_cascade(
            policy,
            dependency_error=RegistrationSetupMinorPolicyDependencyError,
        )
        configuration_digest = _advance_configuration(
            scope=scope,
            resulting_version=resulting_version,
            minor_policy=None,
        )
        target = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.MINOR_POLICY,
            target_id=policy_id,
            change_kind=RegistrationCommandChangeKind.DELETED,
            content_digest=deleted_digest,
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=target,
            targets=(target,),
            configuration_digest=configuration_digest,
            changed_fields=("minor_policy",),
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
            target_id=policy_id,
            configuration_digest=configuration_digest,
        )


def _lock_profile_scope(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
) -> _LockedProfileScope:
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
    with connection.cursor() as cursor:
        cursor.execute("SELECT statement_timestamp()")
        evaluated_at = cursor.fetchone()[0]
    decision = _authorize_before_input_parsing(
        actor=persisted_actor,
        organization_id=organization.id,
        series_id=series.id,
        edition_id=edition.id,
        at=evaluated_at,
    )
    fields = tuple(
        RegistrationProfileExtensionField.objects.select_for_update()
        .filter(organization=organization, edition=edition)
        .order_by("position", "key", "-version", "id")[: MAX_PROFILE_FIELDS + 1]
    )
    if len(fields) > MAX_PROFILE_FIELDS:
        raise RegistrationSetupLimitExceededError
    return _LockedProfileScope(
        organization=organization,
        series=series,
        edition=edition,
        actor=persisted_actor,
        control=control,
        fields=fields,
        decision=decision,
        evaluated_at=evaluated_at,
    )


def _require_profile_lifecycle(scope: _LockedProfileScope) -> None:
    if scope.organization.lifecycle not in {
        Organization.Lifecycle.DRAFT,
        Organization.Lifecycle.ACTIVE,
    } or scope.edition.lifecycle not in {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
    }:
        raise RegistrationSetupLifecycleConflictError


def _profile_field_by_id(
    scope: _LockedProfileScope,
    field_id: UUID,
) -> RegistrationProfileExtensionField:
    field = next((item for item in scope.fields if item.id == field_id), None)
    if field is None:
        raise RegistrationSetupProfileFieldUnavailableError
    return field


def _profile_values(
    *,
    key: object,
    label: object,
    help_text: object,
    field_type: object,
    options: object,
    purpose: object,
    classification: object,
    audience_policy: object | None,
    audience_department_id: object | None,
    attendee_visible: object | None,
    writer_policy: object,
    required: object,
) -> dict[str, object]:
    normalized_key = _normalized_key(key, field="key")
    if normalized_key.startswith(_RESERVED_PROFILE_PREFIXES):
        raise _field_error(
            "key",
            "Use Maru's authoritative domain record for this fact.",
            "registration_setup_profile_field_authoritative_key",
        )
    normalized_type = _closed_choice(
        field_type,
        field="field_type",
        choices=_QUESTION_TYPES,
    )
    normalized_options = _normalized_options(options)
    _validate_options_for_type(
        field_type=normalized_type,
        options=normalized_options,
    )
    if audience_policy is None:
        visible = _strict_boolean(attendee_visible, field="attendee_visible")
        audience: str = (
            ProfileExtensionAudience.SELF
            if visible
            else ProfileExtensionAudience.REGISTRATION_STAFF
        )
    else:
        if attendee_visible is not None:
            raise _field_error(
                "attendee_visible",
                "Use audience_policy instead of the legacy visibility flag.",
                "registration_setup_profile_field_audience_conflict",
            )
        audience = _closed_choice(
            audience_policy,
            field="audience_policy",
            choices=_PROFILE_AUDIENCES,
        )
        visible = audience in {
            ProfileExtensionAudience.SELF,
            ProfileExtensionAudience.CONFIRMED_ATTENDEES,
            ProfileExtensionAudience.PUBLIC,
        }
    department_id = _strict_optional_uuid(
        audience_department_id,
        field="audience_department_id",
    )
    if audience == ProfileExtensionAudience.DEPARTMENT:
        if department_id is None:
            raise _field_error(
                "audience_department_id",
                "Choose one exact active department for this audience.",
                "registration_setup_profile_field_department_required",
            )
    elif department_id is not None:
        raise _field_error(
            "audience_department_id",
            "Only the department audience accepts a department.",
            "registration_setup_profile_field_department_unexpected",
        )
    writer = _closed_choice(
        writer_policy,
        field="writer_policy",
        choices=_PROFILE_WRITERS,
    )
    if not visible and writer in {
        ProfileExtensionWriter.ATTENDEE,
        ProfileExtensionWriter.ATTENDEE_AND_STAFF,
    }:
        raise _field_error(
            "audience_policy",
            "An attendee-writable field must include its owner.",
            "registration_setup_profile_field_writer_audience_conflict",
        )
    return {
        "key": normalized_key,
        "label": _normalized_required_text(
            label,
            field="label",
            maximum=MAX_QUESTION_LABEL_LENGTH,
        ),
        "help_text": _normalized_optional_text(
            help_text,
            field="help_text",
            maximum=MAX_QUESTION_HELP_LENGTH,
        ),
        "field_type": normalized_type,
        "options": normalized_options,
        "purpose": _normalized_required_text(
            purpose,
            field="purpose",
            maximum=MAX_QUESTION_PURPOSE_LENGTH,
        ),
        "classification": _closed_choice(
            classification,
            field="classification",
            choices=_QUESTION_CLASSIFICATIONS,
        ),
        "attendee_visible": visible,
        "audience_policy": audience,
        "audience_department_id": department_id,
        "writer_policy": writer,
        "required": _strict_boolean(required, field="required"),
    }


def _profile_source(
    *,
    scope: _LockedProfileScope,
    source_template_id: UUID | None,
    source_prior_edition_id: UUID | None,
) -> tuple[Any | None, EventEdition | None]:
    if source_template_id and source_prior_edition_id:
        raise _field_error(
            "source_template_id",
            "Choose either a template or a prior edition, not both.",
            "registration_setup_profile_field_source_conflict",
        )
    if source_template_id is not None or source_prior_edition_id is not None:
        field = (
            "source_template_id"
            if source_template_id is not None
            else "source_prior_edition_id"
        )
        raise _field_error(
            field,
            (
                "Profile-definition source copying is unavailable until Maru can "
                "pin an exact source field generation and digest. Create a blank "
                "definition instead."
            ),
            "registration_setup_profile_field_source_unsupported",
        )
    del scope
    return None, None


def _draft_profile_fields(
    fields: tuple[RegistrationProfileExtensionField, ...],
) -> tuple[RegistrationProfileExtensionField, ...]:
    return tuple(item for item in fields if item.status == ProfileExtensionStatus.DRAFT)


def _ordered_profile_fields(
    *,
    fields: tuple[RegistrationProfileExtensionField, ...],
    field: RegistrationProfileExtensionField,
    after_field_id: UUID | None,
) -> tuple[RegistrationProfileExtensionField, ...]:
    remaining = [item for item in fields if item.id != field.id]
    if after_field_id == field.id:
        raise _field_error(
            "after_field_id",
            "Choose another draft field as the ordering anchor.",
            "registration_setup_profile_field_move_invalid",
        )
    if after_field_id is None:
        index = 0
    else:
        anchor = next(
            (i for i, item in enumerate(remaining) if item.id == after_field_id),
            None,
        )
        if anchor is None:
            raise RegistrationSetupProfileFieldUnavailableError
        index = anchor + 1
    remaining.insert(index, field)
    return tuple(remaining)


def _renumber_profile_fields(
    *,
    all_fields: tuple[RegistrationProfileExtensionField, ...],
    ordered_drafts: tuple[RegistrationProfileExtensionField, ...],
    resulting_version: int,
    changed_at: datetime,
) -> tuple[RegistrationProfileExtensionField, ...]:
    fixed_positions = [
        item.position
        for item in all_fields
        if item.status != ProfileExtensionStatus.DRAFT
    ]
    start = ((max(fixed_positions, default=0) // ORDER_POSITION_STEP) + 1) * (
        ORDER_POSITION_STEP
    )
    changed: list[RegistrationProfileExtensionField] = []
    for offset, field in enumerate(ordered_drafts):
        position = start + (offset * ORDER_POSITION_STEP)
        if field.position == position:
            continue
        field.position = position
        if field.review_status != ProfileExtensionReviewStatus.PENDING:
            field.review_status = ProfileExtensionReviewStatus.PENDING
            field.approved_by = None
            field.approved_at = None
        field.last_changed_in_setup_version = resulting_version
        field.updated_at = changed_at
        if not field._state.adding:
            changed.append(field)
    return tuple(changed)


def _persist_profile_fields(
    fields: tuple[RegistrationProfileExtensionField, ...],
) -> None:
    if fields:
        RegistrationProfileExtensionField.objects.bulk_update(
            fields,
            fields=(
                "position",
                "review_status",
                "approved_by",
                "approved_at",
                "last_changed_in_setup_version",
                "updated_at",
            ),
        )


def _advance_profile_setup(
    scope: _LockedProfileScope,
    *,
    resulting_version: int,
) -> None:
    scope.control.aggregate_version = resulting_version
    scope.control.save(update_fields=("aggregate_version", "updated_at"))


def _profile_request_digest(
    *,
    action: str,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    field_id: UUID | None,
    values: dict[str, object],
    source_template_id: UUID | None,
    source_prior_edition_id: UUID | None,
    after_field_id: UUID | None,
    expected_version: int,
    reason: str,
) -> str:
    return canonical_digest(
        {
            "action": action,
            "actor_id": str(actor.pk),
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "field_id": str(field_id) if field_id else None,
            "source_template_id": (
                str(source_template_id) if source_template_id else None
            ),
            "source_prior_edition_id": (
                str(source_prior_edition_id) if source_prior_edition_id else None
            ),
            "after_field_id": str(after_field_id) if after_field_id else None,
            **values,
            "expected_version": expected_version,
            "reason": reason,
        }
    )


def _current_profile_review_receipt(
    *,
    scope: _LockedProfileScope,
    field: RegistrationProfileExtensionField,
) -> RegistrationSetupCommandReceipt:
    """Return the one current receipt proving review of this exact definition.

    Parameters
    ----------
    scope : _LockedProfileScope
        The exact tenant and resource scope of the operation.
    field : RegistrationProfileExtensionField
        The field applied within the audited domain transition.

    Returns
    -------
    RegistrationSetupCommandReceipt
        The RegistrationSetupCommandReceipt produced by current profile review
        receipt.

    Raises
    ------
    RegistrationSetupProfileFieldReviewRequiredError
        If the operation encounters a registration setup profile field review
        required condition.
    """
    review_version = field.last_changed_in_setup_version
    if (
        field.status != ProfileExtensionStatus.DRAFT
        or field.review_status != ProfileExtensionReviewStatus.APPROVED
        or field.approved_by_id is None
        or field.approved_at is None
        or field.approved_at > scope.evaluated_at
        or review_version is None
    ):
        raise RegistrationSetupProfileFieldReviewRequiredError
    receipt = (
        RegistrationSetupCommandReceipt.objects.select_for_update()
        .filter(
            setup=scope.control,
            resulting_version=review_version,
            action=RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED,
            actor_id=field.approved_by_id,
        )
        .first()
    )
    if receipt is None:
        raise RegistrationSetupProfileFieldReviewRequiredError
    approved_digest = _target_digest(
        RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
        field,
    )
    targets = tuple(
        receipt.targets.select_for_update().filter(
            target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
            target_id=field.id,
            change_kind=RegistrationCommandChangeKind.REVIEWED,
            target_schema_version=field.version,
            content_digest=approved_digest,
        )[:2]
    )
    if len(targets) != 1 or receipt.targets.count() != 1:
        raise RegistrationSetupProfileFieldReviewRequiredError
    try:
        audit = _require_profile_command_evidence(
            scope=scope,
            receipt=receipt,
            primary_target_id=field.id,
        )
    except RegistrationSetupStateConflictError as error:
        raise RegistrationSetupProfileFieldReviewRequiredError from error
    expected_request_digest = _profile_request_digest(
        action=RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED,
        actor=receipt.actor,
        organization_id=scope.organization.id,
        series_id=scope.series.id,
        edition_id=scope.edition.id,
        field_id=field.id,
        values={},
        source_template_id=None,
        source_prior_edition_id=None,
        after_field_id=None,
        expected_version=review_version - 1,
        reason=receipt.reason,
    )
    if (
        review_version <= 1
        or receipt.request_digest != expected_request_digest
        or audit.occurred_at != field.approved_at
        or audit.changed_fields != ["review_status", "approved_by", "approved_at"]
    ):
        raise RegistrationSetupProfileFieldReviewRequiredError
    return receipt


def _require_profile_successor_origin(
    *,
    scope: _LockedProfileScope,
    field: RegistrationProfileExtensionField,
) -> None:
    """Require the canonical command graph for a successor definition.

    Parameters
    ----------
    scope : _LockedProfileScope
        The exact tenant and resource scope of the operation.
    field : RegistrationProfileExtensionField
        The field applied within the audited domain transition.

    Raises
    ------
    RegistrationSetupProfileFieldSuccessorConflictError
        If the operation encounters a registration setup profile field successor
        conflict condition.
    """
    if field.supersedes_id is None:
        return
    creation_version = field.created_in_setup_version
    if creation_version is None or creation_version <= 1:
        raise RegistrationSetupProfileFieldSuccessorConflictError
    receipts = tuple(
        RegistrationSetupCommandReceipt.objects.select_for_update().filter(
            setup=scope.control,
            resulting_version=creation_version,
            action=(
                RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_SUCCESSOR_STARTED
            ),
        )[:2]
    )
    if len(receipts) != 1 or receipts[0].actor_id != field.created_by_id:
        raise RegistrationSetupProfileFieldSuccessorConflictError
    receipt = receipts[0]
    try:
        _require_profile_command_evidence(
            scope=scope,
            receipt=receipt,
            primary_target_id=field.id,
        )
    except RegistrationSetupStateConflictError as error:
        raise RegistrationSetupProfileFieldSuccessorConflictError from error
    expected_request_digest = _profile_request_digest(
        action=RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_SUCCESSOR_STARTED,
        actor=receipt.actor,
        organization_id=scope.organization.id,
        series_id=scope.series.id,
        edition_id=scope.edition.id,
        field_id=field.supersedes_id,
        values={},
        source_template_id=None,
        source_prior_edition_id=None,
        after_field_id=None,
        expected_version=creation_version - 1,
        reason=receipt.reason,
    )
    if receipt.request_digest != expected_request_digest:
        raise RegistrationSetupProfileFieldSuccessorConflictError


def create_registration_profile_extension_field(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    key: str,
    label: str,
    help_text: str,
    field_type: str,
    options: list[str],
    purpose: str,
    classification: str,
    audience_policy: str | None = None,
    audience_department_id: UUID | None = None,
    attendee_visible: bool | None = None,
    writer_policy: str,
    required: bool,
    source_template_id: UUID | None,
    source_prior_edition_id: UUID | None,
    after_field_id: UUID | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Create registration profile extension field.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    key : str
        The stable lookup key.
    label : str
        The human-readable label.
    help_text : str
        The explanatory text shown to the user.
    field_type : str
        The closed field-type code.
    options : list[str]
        The permitted operation options.
    purpose : str
        The documented purpose of the operation.
    classification : str
        The closed data-classification code.
    audience_policy : str | None, default=None
        The closed audience policy governing validation or disclosure.
    audience_department_id : UUID | None, default=None
        The identifier of the audience department.
    attendee_visible : bool | None, default=None
        The attendee visible applied within the audited domain transition.
    writer_policy : str
        The closed writer policy governing validation or disclosure.
    required : bool
        Whether the input is required.
    source_template_id : UUID | None
        The identifier of the source template.
    source_prior_edition_id : UUID | None
        The identifier of the source prior edition.
    after_field_id : UUID | None
        The identifier of the after field.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    RegistrationSetupLimitExceededError
        If the operation encounters a registration setup limit exceeded
        condition.
    _field_error
        If the operation encounters a field error condition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    values = _profile_values(
        key=key,
        label=label,
        help_text=help_text,
        field_type=field_type,
        options=options,
        purpose=purpose,
        classification=classification,
        audience_policy=audience_policy,
        audience_department_id=audience_department_id,
        attendee_visible=attendee_visible,
        writer_policy=writer_policy,
        required=required,
    )
    source_template_id = _strict_optional_uuid(
        source_template_id,
        field="source_template_id",
    )
    source_prior_edition_id = _strict_optional_uuid(
        source_prior_edition_id,
        field="source_prior_edition_id",
    )
    after_field_id = _strict_optional_uuid(after_field_id, field="after_field_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_CREATED
    request_digest = _profile_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        field_id=None,
        values=values,
        source_template_id=source_template_id,
        source_prior_edition_id=source_prior_edition_id,
        after_field_id=after_field_id,
        expected_version=expected_version,
        reason=normalized_reason,
    )
    with transaction.atomic():
        scope = _lock_profile_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                target_id=None,
            )
        _require_profile_lifecycle(scope)
        current_version = _require_current_version(scope, expected_version)
        if len(scope.fields) >= MAX_PROFILE_FIELDS:
            raise RegistrationSetupLimitExceededError
        if any(item.key == values["key"] for item in scope.fields):
            raise _field_error(
                "key",
                "This edition already has a definition for that stable key.",
                "registration_setup_profile_field_key_duplicate",
            )
        template, prior = _profile_source(
            scope=scope,
            source_template_id=source_template_id,
            source_prior_edition_id=source_prior_edition_id,
        )
        resulting_version = current_version + 1
        field = RegistrationProfileExtensionField(
            organization=scope.organization,
            edition=scope.edition,
            version=1,
            position=0,
            source_template=template,
            source_prior_edition=prior,
            review_status=ProfileExtensionReviewStatus.PENDING,
            status=ProfileExtensionStatus.DRAFT,
            created_by=scope.actor,
            created_in_setup_version=resulting_version,
            last_changed_in_setup_version=resulting_version,
            **values,
        )
        drafts = _draft_profile_fields(scope.fields)
        ordered = _ordered_profile_fields(
            fields=drafts,
            field=field,
            after_field_id=after_field_id,
        )
        changed = _renumber_profile_fields(
            all_fields=(*scope.fields, field),
            ordered_drafts=ordered,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        field.full_clean()
        field.save(force_insert=True)
        _persist_profile_fields(changed)
        _advance_profile_setup(scope, resulting_version=resulting_version)
        targets = (
            _TargetEvidence(
                target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                target_id=field.id,
                change_kind=RegistrationCommandChangeKind.CREATED,
                content_digest=_target_digest(
                    RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                    field,
                ),
                target_schema_version=field.version,
            ),
            *(
                _TargetEvidence(
                    target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                    target_id=moved.id,
                    change_kind=RegistrationCommandChangeKind.MOVED,
                    content_digest=_target_digest(
                        RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                        moved,
                    ),
                    target_schema_version=moved.version,
                )
                for moved in changed
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=targets[0],
            targets=targets,
            configuration_digest="",
            changed_fields=("profile_fields", "profile_field_order"),
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
            target_id=field.id,
            configuration_digest="",
        )


def update_registration_profile_extension_field(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    field_id: UUID,
    key: str,
    label: str,
    help_text: str,
    field_type: str,
    options: list[str],
    purpose: str,
    classification: str,
    audience_policy: str | None = None,
    audience_department_id: UUID | None = None,
    attendee_visible: bool | None = None,
    writer_policy: str,
    required: bool,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Update registration profile extension field.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    field_id : UUID
        The identifier of the field.
    key : str
        The stable lookup key.
    label : str
        The human-readable label.
    help_text : str
        The explanatory text shown to the user.
    field_type : str
        The closed field-type code.
    options : list[str]
        The permitted operation options.
    purpose : str
        The documented purpose of the operation.
    classification : str
        The closed data-classification code.
    audience_policy : str | None, default=None
        The closed audience policy governing validation or disclosure.
    audience_department_id : UUID | None, default=None
        The identifier of the audience department.
    attendee_visible : bool | None, default=None
        The attendee visible applied within the audited domain transition.
    writer_policy : str
        The closed writer policy governing validation or disclosure.
    required : bool
        Whether the input is required.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    RegistrationSetupProfileFieldImmutableError
        If the operation encounters a registration setup profile field immutable
        condition.
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    _field_error
        If the operation encounters a field error condition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    field_id = _strict_uuid(field_id, field="field_id")
    values = _profile_values(
        key=key,
        label=label,
        help_text=help_text,
        field_type=field_type,
        options=options,
        purpose=purpose,
        classification=classification,
        audience_policy=audience_policy,
        audience_department_id=audience_department_id,
        attendee_visible=attendee_visible,
        writer_policy=writer_policy,
        required=required,
    )
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_UPDATED
    request_digest = _profile_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        field_id=field_id,
        values=values,
        source_template_id=None,
        source_prior_edition_id=None,
        after_field_id=None,
        expected_version=expected_version,
        reason=normalized_reason,
    )
    with transaction.atomic():
        scope = _lock_profile_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                target_id=field_id,
            )
        _require_profile_lifecycle(scope)
        current_version = _require_current_version(scope, expected_version)
        field = _profile_field_by_id(scope, field_id)
        if field.status != ProfileExtensionStatus.DRAFT:
            raise RegistrationSetupProfileFieldImmutableError
        if field.supersedes_id is not None and values["key"] != field.key:
            raise _field_error(
                "key",
                "A successor keeps its predecessor's stable key.",
                "registration_setup_profile_field_successor_key_immutable",
            )
        if field.supersedes_id is None and any(
            item.id != field.id and item.key == values["key"] for item in scope.fields
        ):
            raise _field_error(
                "key",
                "This edition already has a definition for that stable key.",
                "registration_setup_profile_field_key_duplicate",
            )
        changed_fields = tuple(
            name for name, value in values.items() if getattr(field, name) != value
        )
        review_reset = (
            field.review_status != ProfileExtensionReviewStatus.PENDING
            or field.approved_by_id is not None
            or field.approved_at is not None
        )
        if not changed_fields and not review_reset:
            raise RegistrationSetupStateConflictError
        resulting_version = current_version + 1
        for name, value in values.items():
            setattr(field, name, value)
        field.review_status = ProfileExtensionReviewStatus.PENDING
        field.approved_by = None
        field.approved_at = None
        field.last_changed_in_setup_version = resulting_version
        field.save(
            update_fields=(
                *values.keys(),
                "review_status",
                "approved_by",
                "approved_at",
                "last_changed_in_setup_version",
                "updated_at",
            )
        )
        _advance_profile_setup(scope, resulting_version=resulting_version)
        target = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
            target_id=field.id,
            change_kind=RegistrationCommandChangeKind.UPDATED,
            content_digest=_target_digest(
                RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                field,
            ),
            target_schema_version=field.version,
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=target,
            targets=(target,),
            configuration_digest="",
            changed_fields=(
                *changed_fields,
                *(("review_status",) if review_reset else ()),
            ),
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
            target_id=field.id,
            configuration_digest="",
        )


def move_registration_profile_extension_field(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    field_id: UUID,
    after_field_id: UUID | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Move registration profile extension field.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    field_id : UUID
        The identifier of the field.
    after_field_id : UUID | None
        The identifier of the after field.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The registration definition command result.

    Raises
    ------
    RegistrationSetupProfileFieldImmutableError
        If the operation encounters a registration setup profile field immutable
        condition.
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    field_id = _strict_uuid(field_id, field="field_id")
    after_field_id = _strict_optional_uuid(after_field_id, field="after_field_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_MOVED
    request_digest = _profile_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        field_id=field_id,
        values={},
        source_template_id=None,
        source_prior_edition_id=None,
        after_field_id=after_field_id,
        expected_version=expected_version,
        reason=normalized_reason,
    )
    with transaction.atomic():
        scope = _lock_profile_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                target_id=field_id,
            )
        _require_profile_lifecycle(scope)
        current_version = _require_current_version(scope, expected_version)
        field = _profile_field_by_id(scope, field_id)
        if field.status != ProfileExtensionStatus.DRAFT:
            raise RegistrationSetupProfileFieldImmutableError
        drafts = _draft_profile_fields(scope.fields)
        ordered = _ordered_profile_fields(
            fields=drafts,
            field=field,
            after_field_id=after_field_id,
        )
        if tuple(item.id for item in ordered) == tuple(item.id for item in drafts):
            raise RegistrationSetupStateConflictError
        resulting_version = current_version + 1
        changed = _renumber_profile_fields(
            all_fields=scope.fields,
            ordered_drafts=ordered,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        if all(item.id != field.id for item in changed):
            field.last_changed_in_setup_version = resulting_version
            field.updated_at = scope.evaluated_at
            changed = (*changed, field)
        _persist_profile_fields(changed)
        _advance_profile_setup(scope, resulting_version=resulting_version)
        targets = tuple(
            _TargetEvidence(
                target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                target_id=moved.id,
                change_kind=RegistrationCommandChangeKind.MOVED,
                content_digest=_target_digest(
                    RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                    moved,
                ),
                target_schema_version=moved.version,
            )
            for moved in changed
        )
        primary = next(item for item in targets if item.target_id == field.id)
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=primary,
            targets=targets,
            configuration_digest="",
            changed_fields=("profile_field_order",),
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
            target_id=field.id,
            configuration_digest="",
        )


def approve_registration_profile_extension_field(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    field_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Approve one exact draft generation with server-derived reviewer evidence.

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
    field_id : UUID
        The field identifier within the requested scope.
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
    RegistrationDefinitionCommandResult
        The RegistrationDefinitionCommandResult produced by approve registration
        profile extension field.

    Raises
    ------
    RegistrationSetupProfileFieldImmutableError
        If the operation encounters a registration setup profile field immutable
        condition.
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    field_id = _strict_uuid(field_id, field="field_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_REVIEWED
    request_digest = _profile_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        field_id=field_id,
        values={},
        source_template_id=None,
        source_prior_edition_id=None,
        after_field_id=None,
        expected_version=expected_version,
        reason=normalized_reason,
    )
    with transaction.atomic():
        scope = _lock_profile_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                target_id=field_id,
            )
        _require_profile_lifecycle(scope)
        current_version = _require_current_version(scope, expected_version)
        field = _profile_field_by_id(scope, field_id)
        if field.status != ProfileExtensionStatus.DRAFT:
            raise RegistrationSetupProfileFieldImmutableError
        if (
            field.review_status == ProfileExtensionReviewStatus.APPROVED
            or field.approved_by_id is not None
            or field.approved_at is not None
        ):
            raise RegistrationSetupStateConflictError
        field.full_clean()
        resulting_version = current_version + 1
        field.review_status = ProfileExtensionReviewStatus.APPROVED
        field.approved_by = scope.actor
        field.approved_at = scope.evaluated_at
        field.last_changed_in_setup_version = resulting_version
        field.save(
            update_fields=(
                "review_status",
                "approved_by",
                "approved_at",
                "last_changed_in_setup_version",
                "updated_at",
            )
        )
        _advance_profile_setup(scope, resulting_version=resulting_version)
        target = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
            target_id=field.id,
            change_kind=RegistrationCommandChangeKind.REVIEWED,
            content_digest=_target_digest(
                RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                field,
            ),
            target_schema_version=field.version,
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=target,
            targets=(target,),
            configuration_digest="",
            changed_fields=("review_status", "approved_by", "approved_at"),
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
            target_id=field.id,
            configuration_digest="",
        )


def start_registration_profile_extension_field_successor(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    field_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Copy one active definition into its explicit next-version draft.

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
    field_id : UUID
        The field identifier within the requested scope.
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
    RegistrationDefinitionCommandResult
        The RegistrationDefinitionCommandResult produced by start registration
        profile extension field successor.

    Raises
    ------
    RegistrationSetupProfileFieldSuccessorConflictError
        If the operation encounters a registration setup profile field successor
        conflict condition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    field_id = _strict_uuid(field_id, field="field_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_SUCCESSOR_STARTED
    request_digest = _profile_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        field_id=field_id,
        values={},
        source_template_id=None,
        source_prior_edition_id=None,
        after_field_id=None,
        expected_version=expected_version,
        reason=normalized_reason,
    )
    with transaction.atomic():
        scope = _lock_profile_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                target_id=None,
            )
        _require_profile_lifecycle(scope)
        current_version = _require_current_version(scope, expected_version)
        active = _profile_field_by_id(scope, field_id)
        if active.status != ProfileExtensionStatus.ACTIVE:
            raise RegistrationSetupProfileFieldSuccessorConflictError
        same_key_versions = tuple(
            item for item in scope.fields if item.key == active.key
        )
        if len(scope.fields) >= MAX_PROFILE_FIELDS or any(
            item.status == ProfileExtensionStatus.DRAFT for item in same_key_versions
        ):
            raise RegistrationSetupProfileFieldSuccessorConflictError
        next_definition_version = max(item.version for item in same_key_versions) + 1
        resulting_version = current_version + 1
        successor = RegistrationProfileExtensionField(
            organization=scope.organization,
            edition=scope.edition,
            key=active.key,
            version=next_definition_version,
            supersedes=active,
            label=active.label,
            help_text=active.help_text,
            field_type=active.field_type,
            options=list(active.options),
            purpose=active.purpose,
            classification=active.classification,
            attendee_visible=active.attendee_visible,
            audience_policy=active.audience_policy,
            audience_department_id=active.audience_department_id,
            writer_policy=active.writer_policy,
            required=active.required,
            position=active.position,
            source_template=None,
            source_prior_edition=None,
            review_status=ProfileExtensionReviewStatus.PENDING,
            status=ProfileExtensionStatus.DRAFT,
            created_by=scope.actor,
            created_in_setup_version=resulting_version,
            last_changed_in_setup_version=resulting_version,
        )
        successor.save(force_insert=True)
        _advance_profile_setup(scope, resulting_version=resulting_version)
        target = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
            target_id=successor.id,
            change_kind=RegistrationCommandChangeKind.CREATED,
            content_digest=_target_digest(
                RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                successor,
            ),
            target_schema_version=successor.version,
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=target,
            targets=(target,),
            configuration_digest="",
            changed_fields=("profile_fields", "supersedes"),
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
            target_id=successor.id,
            configuration_digest="",
        )


def activate_registration_profile_extension_field(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    field_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Activate an exactly reviewed draft and retire only its superseded version.

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
    field_id : UUID
        The field identifier within the requested scope.
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
    RegistrationDefinitionCommandResult
        The RegistrationDefinitionCommandResult produced by activate
        registration profile extension field.

    Raises
    ------
    RegistrationSetupProfileFieldImmutableError
        If the operation encounters a registration setup profile field immutable
        condition.
    RegistrationSetupProfileFieldSuccessorConflictError
        If the operation encounters a registration setup profile field successor
        conflict condition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    field_id = _strict_uuid(field_id, field="field_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_ACTIVATED
    request_digest = _profile_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        field_id=field_id,
        values={},
        source_template_id=None,
        source_prior_edition_id=None,
        after_field_id=None,
        expected_version=expected_version,
        reason=normalized_reason,
    )
    with transaction.atomic():
        scope = _lock_profile_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                target_id=field_id,
            )
        _require_profile_lifecycle(scope)
        current_version = _require_current_version(scope, expected_version)
        field = _profile_field_by_id(scope, field_id)
        if field.status != ProfileExtensionStatus.DRAFT:
            raise RegistrationSetupProfileFieldImmutableError
        _require_profile_successor_origin(scope=scope, field=field)
        _current_profile_review_receipt(scope=scope, field=field)
        active_versions = tuple(
            item
            for item in scope.fields
            if item.key == field.key and item.status == ProfileExtensionStatus.ACTIVE
        )
        superseded = None
        if field.supersedes_id is None:
            if active_versions:
                raise RegistrationSetupProfileFieldSuccessorConflictError
        else:
            superseded = next(
                (item for item in scope.fields if item.id == field.supersedes_id),
                None,
            )
            if (
                superseded is None
                or superseded.status != ProfileExtensionStatus.ACTIVE
                or superseded.key != field.key
                or superseded.version >= field.version
                or field.version
                != max(item.version for item in scope.fields if item.key == field.key)
                or tuple(item.id for item in active_versions) != (superseded.id,)
                or any(
                    item.id != field.id
                    and item.key == field.key
                    and item.status != ProfileExtensionStatus.RETIRED
                    and item.supersedes_id == superseded.id
                    for item in scope.fields
                )
            ):
                raise RegistrationSetupProfileFieldSuccessorConflictError
        resulting_version = current_version + 1
        if superseded is not None:
            superseded.status = ProfileExtensionStatus.RETIRED
            superseded.last_changed_in_setup_version = resulting_version
            superseded.save(
                update_fields=(
                    "status",
                    "last_changed_in_setup_version",
                    "updated_at",
                )
            )
        field.status = ProfileExtensionStatus.ACTIVE
        field.last_changed_in_setup_version = resulting_version
        field.save(
            update_fields=(
                "status",
                "last_changed_in_setup_version",
                "updated_at",
            )
        )
        _advance_profile_setup(scope, resulting_version=resulting_version)
        primary = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
            target_id=field.id,
            change_kind=RegistrationCommandChangeKind.ACTIVATED,
            content_digest=_target_digest(
                RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                field,
            ),
            target_schema_version=field.version,
        )
        targets = (
            primary,
            *(
                (
                    _TargetEvidence(
                        target_kind=(
                            RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD
                        ),
                        target_id=superseded.id,
                        change_kind=RegistrationCommandChangeKind.RETIRED,
                        content_digest=_target_digest(
                            RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                            superseded,
                        ),
                        target_schema_version=superseded.version,
                    ),
                )
                if superseded is not None
                else ()
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=primary,
            targets=targets,
            configuration_digest="",
            changed_fields=(
                "status",
                *(("superseded_status",) if superseded is not None else ()),
            ),
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
            target_id=field.id,
            configuration_digest="",
        )


def retire_registration_profile_extension_field(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    field_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RegistrationDefinitionCommandResult:
    """Retire registration profile extension field.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    series_id : UUID
        The identifier of the series.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    field_id : UUID
        The identifier of the field.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    RegistrationDefinitionCommandResult
        The registration definition command result.

    Raises
    ------
    RegistrationSetupProfileFieldDependencyError
        If the operation encounters a registration setup profile field
        dependency condition.
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    _authorize_before_input_parsing(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    field_id = _strict_uuid(field_id, field="field_id")
    expected_version = _expected_version(expected_version)
    normalized_reason = _reason(reason)
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    source_channel = _source_channel(source_channel)
    action = RegistrationSetupCommandReceipt.Action.PROFILE_FIELD_RETIRED
    request_digest = _profile_request_digest(
        action=action,
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        field_id=field_id,
        values={},
        source_template_id=None,
        source_prior_edition_id=None,
        after_field_id=None,
        expected_version=expected_version,
        reason=normalized_reason,
    )
    with transaction.atomic():
        scope = _lock_profile_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _result_from_receipt(
                scope=scope,
                receipt=replay,
                action=action,
                request_digest=request_digest,
                target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                target_id=field_id,
            )
        _require_profile_lifecycle(scope)
        current_version = _require_current_version(scope, expected_version)
        field = _profile_field_by_id(scope, field_id)
        if field.status == ProfileExtensionStatus.RETIRED:
            raise RegistrationSetupStateConflictError
        if field.status == ProfileExtensionStatus.ACTIVE and any(
            item.status == ProfileExtensionStatus.DRAFT
            and item.supersedes_id == field.id
            for item in scope.fields
        ):
            raise RegistrationSetupProfileFieldDependencyError
        resulting_version = current_version + 1
        field.status = ProfileExtensionStatus.RETIRED
        field.last_changed_in_setup_version = resulting_version
        field.save(
            update_fields=(
                "status",
                "last_changed_in_setup_version",
                "updated_at",
            )
        )
        remaining_drafts = tuple(
            item
            for item in scope.fields
            if item.id != field.id and item.status == ProfileExtensionStatus.DRAFT
        )
        changed = _renumber_profile_fields(
            all_fields=scope.fields,
            ordered_drafts=remaining_drafts,
            resulting_version=resulting_version,
            changed_at=scope.evaluated_at,
        )
        _persist_profile_fields(changed)
        _advance_profile_setup(scope, resulting_version=resulting_version)
        primary = _TargetEvidence(
            target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
            target_id=field.id,
            change_kind=RegistrationCommandChangeKind.RETIRED,
            content_digest=_target_digest(
                RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                field,
            ),
            target_schema_version=field.version,
        )
        targets = (
            primary,
            *(
                _TargetEvidence(
                    target_kind=RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                    target_id=moved.id,
                    change_kind=RegistrationCommandChangeKind.MOVED,
                    content_digest=_target_digest(
                        RegistrationSetupCommandTarget.TargetKind.PROFILE_FIELD,
                        moved,
                    ),
                    target_schema_version=moved.version,
                )
                for moved in changed
            ),
        )
        receipt = _append_evidence(
            scope=scope,
            action=action,
            resulting_version=resulting_version,
            primary=primary,
            targets=targets,
            configuration_digest="",
            changed_fields=("status", "profile_field_order"),
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
            target_id=field.id,
            configuration_digest="",
        )


__all__ = [
    "RegistrationDefinitionCommandResult",
    "RegistrationSetupMinorPolicyDependencyError",
    "RegistrationSetupMinorPolicyUnavailableError",
    "RegistrationSetupProductDependencyError",
    "RegistrationSetupProductUnavailableError",
    "RegistrationSetupProfileFieldDependencyError",
    "RegistrationSetupProfileFieldImmutableError",
    "RegistrationSetupProfileFieldReviewRequiredError",
    "RegistrationSetupProfileFieldSuccessorConflictError",
    "RegistrationSetupProfileFieldUnavailableError",
    "RegistrationSetupQuestionDependencyError",
    "RegistrationSetupQuestionUnavailableError",
    "activate_registration_profile_extension_field",
    "approve_registration_profile_extension_field",
    "create_admission_product",
    "create_registration_profile_extension_field",
    "create_registration_question",
    "delete_admission_product",
    "delete_registration_question",
    "move_admission_product",
    "move_registration_profile_extension_field",
    "move_registration_question",
    "remove_minor_registration_policy",
    "retire_registration_profile_extension_field",
    "set_minor_registration_policy",
    "start_registration_profile_extension_field_successor",
    "update_admission_product",
    "update_registration_profile_extension_field",
    "update_registration_question",
]
