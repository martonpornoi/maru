"""Transactional commands for the typed application portfolio."""
# ruff: noqa: N818, PLR0912, PLR2004

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from maru.applications.adoption import (
    profile_allows_application_eligibility,
    profile_allows_application_reviewer_role,
    profile_allows_application_self,
    profile_allows_application_source,
    profile_allows_application_target,
)
from maru.applications.answer_values import condition_matches, normalize_answer_value
from maru.applications.legacy_targets import (
    LEGACY_APPLICATION_TARGET_KINDS,
    is_legacy_application_target,
)
from maru.applications.models import (
    MAX_QUESTIONS,
    MAX_SECTIONS,
    AnswerSource,
    ApplicationAnswerRevision,
    ApplicationClassification,
    ApplicationCommandReceipt,
    ApplicationDefinition,
    ApplicationDefinitionStatus,
    ApplicationOwnerDepartment,
    ApplicationQuestion,
    ApplicationReviewDecision,
    ApplicationReviewerPerson,
    ApplicationReviewerRole,
    ApplicationSection,
    ApplicationState,
    ApplicationSubmission,
    ApplicationTargetRecord,
    ProgrammeCommandReceipt,
    ProgrammeImportCommandReceipt,
    ProgrammeReviewReceipt,
    ReviewDecisionKind,
    ReviewerBasis,
)
from maru.applications.retry_namespace import lock_applications_retry_namespace
from maru.applications.source_adapters import applicant_is_eligible, source_bound_value
from maru.applications.starters import application_starter_for_profile
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.models import RoleAssignment, RoleBundle
from maru.authorization.policy import (
    current_role_assignment_ids,
    decide,
    resolve_edition_target,
    resolve_self_target,
)
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.models import Account

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID


class ApplicationCommandError(RuntimeError):
    """Signal application command."""

    reason_code = "application_command_conflict"


class ApplicationAuthorizationDenied(ApplicationCommandError):
    """Signal application authorization denied."""

    reason_code = "application_authorization_denied"


class ApplicationUnavailable(ApplicationCommandError):
    """Signal application unavailable."""

    reason_code = "application_unavailable"


class ApplicationStateConflict(ApplicationCommandError):
    """Signal application state conflict."""

    reason_code = "application_state_conflict"


class ApplicationVersionConflict(ApplicationCommandError):
    """Signal application version conflict."""

    reason_code = "application_version_conflict"


class ApplicationIdempotencyConflict(ApplicationCommandError):
    """Signal application idempotency conflict."""

    reason_code = "application_idempotency_conflict"


class ApplicationEligibilityDenied(ApplicationCommandError):
    """Signal application eligibility denied."""

    reason_code = "application_eligibility_denied"


@dataclass(frozen=True, slots=True)
class ApplicationCommandResult:
    """Describe application command result.

    Attributes
    ----------
    receipt_id
        The receipt identifier within the requested scope.
    definition_id
        The definition identifier within the requested scope.
    submission_id
        The submission identifier within the requested scope.
    target_id
        The target identifier within the requested scope.
    resulting_version
        The expected resulting version used to reject stale updates.
    replayed
        The replayed retained in this immutable projection.
    """

    receipt_id: UUID
    definition_id: UUID | None
    submission_id: UUID | None
    target_id: UUID | None
    resulting_version: int
    replayed: bool


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _result(
    receipt: ApplicationCommandReceipt, *, replayed: bool
) -> ApplicationCommandResult:
    return ApplicationCommandResult(
        receipt_id=receipt.id,
        definition_id=receipt.definition_id,
        submission_id=receipt.submission_id,
        target_id=receipt.target_id,
        resulting_version=receipt.resulting_version,
        replayed=replayed,
    )


def _replay(
    *,
    actor: Account,
    edition_id: UUID,
    retry_key: UUID,
    request_digest: str,
) -> ApplicationCommandResult | None:
    lock_applications_retry_namespace(
        edition_id=edition_id,
        actor_id=actor.id,
        retry_key=retry_key,
    )
    receipt = (
        ApplicationCommandReceipt.objects.select_for_update()
        .filter(edition_id=edition_id, actor_id=actor.id, retry_key=retry_key)
        .first()
    )
    if receipt is None:
        if (
            ProgrammeCommandReceipt.objects.select_for_update()
            .filter(
                edition_id=edition_id,
                actor_id=actor.id,
                retry_key=retry_key,
            )
            .exists()
            or ProgrammeImportCommandReceipt.objects.select_for_update()
            .filter(
                edition_id=edition_id,
                actor_id=actor.id,
                retry_key=retry_key,
            )
            .exists()
            or ProgrammeReviewReceipt.objects.select_for_update()
            .filter(edition_id=edition_id, actor_id=actor.id, retry_key=retry_key)
            .exists()
        ):
            raise ApplicationIdempotencyConflict
        return None
    if receipt.request_digest != request_digest:
        raise ApplicationIdempotencyConflict
    return _result(receipt, replayed=True)


def _edition_target(
    *, actor: Account, organization_id: UUID, edition_id: UUID, capability_code: str
) -> tuple[Account, EventEdition]:
    current_actor = Account.objects.filter(id=actor.id, is_active=True).first()
    edition = (
        EventEdition.objects.select_related("organization", "series")
        .filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .first()
    )
    target = resolve_edition_target(
        organization_id=organization_id, edition_id=edition_id
    )
    decision = (
        decide(
            principal=current_actor, capability_code=capability_code, resource=target
        )
        if current_actor is not None and target is not None
        else None
    )
    if (
        current_actor is None
        or edition is None
        or decision is None
        or not decision.allowed
    ):
        raise ApplicationAuthorizationDenied
    return current_actor, edition


def _self_target(
    *, actor: Account, organization_id: UUID, edition_id: UUID, capability_code: str
) -> tuple[Account, EventEdition]:
    current_actor = Account.objects.filter(id=actor.id, is_active=True).first()
    edition = (
        EventEdition.objects.select_related("organization", "series")
        .filter(id=edition_id, organization_id=organization_id)
        .first()
    )
    target = (
        resolve_self_target(
            principal=current_actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if current_actor is not None
        else None
    )
    decision = (
        decide(
            principal=current_actor, capability_code=capability_code, resource=target
        )
        if current_actor is not None and target is not None
        else None
    )
    if (
        current_actor is None
        or edition is None
        or decision is None
        or not decision.allowed
        or not profile_allows_application_self(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
        )
    ):
        raise ApplicationAuthorizationDenied
    return current_actor, edition


def _record_evidence(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    action: str,
    capability_code: str,
    request_digest: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    resulting_version: int,
    definition: ApplicationDefinition | None = None,
    submission: ApplicationSubmission | None = None,
    target_id: UUID | None = None,
    changed_fields: tuple[str, ...] = (),
) -> ApplicationCommandResult:
    receipt = ApplicationCommandReceipt.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        actor=actor,
        action=action,
        retry_key=retry_key,
        request_digest=request_digest,
        correlation_id=correlation_id,
        source_channel=source_channel,
        definition=definition,
        submission=submission,
        target_id=target_id,
        resulting_version=resulting_version,
    )
    aggregate = submission or definition
    if aggregate is None:
        raise RuntimeError("Application evidence requires one aggregate.")
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=capability_code,
            operation=f"applications.{action}",
            target_type=(
                "applications.submission" if submission else "applications.definition"
            ),
            target_id=aggregate.id,
            outcome="allow",
            reason_code=f"applications_{action}",
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=changed_fields,
            idempotency_key_hash=hashlib.sha256(str(retry_key).encode()).hexdigest(),
        )
    )
    event_name = (
        "applications.submission.changed.v1"
        if submission
        else "applications.definition.changed.v1"
    )
    if submission is not None:
        payload: dict[str, object] = {
            "action": action,
            "state": submission.state,
            "target_adapter_kind": submission.definition.target_adapter_kind,
        }
    else:
        current_definition = cast("ApplicationDefinition", definition)
        payload = {
            "action": action,
            "definition_code": current_definition.code,
            "definition_version": str(current_definition.version),
        }
    publish_domain_event(
        DomainEventRecord(
            event_name=event_name,
            schema_version=1,
            organization_id=organization_id,
            event_edition_id=edition_id,
            aggregate_type=(
                "application_submission" if submission else "application_definition"
            ),
            aggregate_id=aggregate.id,
            aggregate_version=resulting_version,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=None,
            actor_kind="account",
            actor_id=actor.id,
            retention_class="domain-sensitive"
            if definition and definition.is_sensitive
            else "domain-standard",
        )
    )
    return _result(receipt, replayed=False)


def _locked_definition(
    *, organization_id: UUID, edition_id: UUID, definition_id: UUID
) -> ApplicationDefinition:
    definition = (
        ApplicationDefinition.objects.select_for_update()
        .select_related("edition")
        .filter(
            id=definition_id,
            organization_id=organization_id,
            edition_id=edition_id,
            target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .first()
    )
    if definition is None:
        raise ApplicationUnavailable
    return definition


def _check_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise ApplicationVersionConflict


@transaction.atomic
def create_definition_from_starter(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    starter_code: str,
    opens_at: datetime,
    closes_at: datetime,
    applicant_edit_until: datetime,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> ApplicationCommandResult:
    """Create definition from starter.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    starter_code : str
        The immutable starter-catalog code.
    opens_at : datetime
        The time at which the window opens.
    closes_at : datetime
        The time at which the window closes.
    applicant_edit_until : datetime
        The timezone-aware boundary for applicant edit until.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.

    Returns
    -------
    ApplicationCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    actor, edition = _edition_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.manage_definitions",
    )
    request_digest = _digest(
        {
            "operation": "definition.create",
            "starter_code": starter_code,
            "opens_at": opens_at,
            "closes_at": closes_at,
            "applicant_edit_until": applicant_edit_until,
        }
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    starter = application_starter_for_profile(
        profile_code=edition.adoption_profile_code,
        profile_version=edition.adoption_profile_version,
        starter_code=starter_code,
    )
    if (
        starter is None
        or starter.is_external
        or not is_legacy_application_target(cast("str", starter.target_adapter_kind))
    ):
        raise ValidationError(
            {"starter_code": "Choose an applications-owned starter."},
            code="application_starter_unavailable",
        )
    ApplicationDefinition.objects.select_for_update().filter(
        edition_id=edition_id, code=starter.code
    ).exists()
    if ApplicationDefinition.objects.filter(
        edition_id=edition_id, code=starter.code
    ).exists():
        raise ApplicationStateConflict
    definition = ApplicationDefinition.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        code=starter.code,
        version=1,
        target_adapter_kind=cast("str", starter.target_adapter_kind),
        name=starter.name,
        description=starter.description,
        purpose=starter.purpose,
        classification=starter.classification,
        eligibility_kind=starter.eligibility_kind,
        max_submissions_per_person=starter.maximum_submissions,
        opens_at=opens_at,
        closes_at=closes_at,
        applicant_edit_until=applicant_edit_until,
        minimum_age=starter.minimum_age,
        audience_policy_code=starter.audience_policy_code,
        retention_policy_code=starter.retention_policy_code,
        age_policy_code=starter.age_policy_code,
        created_by=actor,
    )
    section = ApplicationSection.objects.create(
        definition=definition,
        key="application",
        title="Application",
        help_text="Complete the edition-owned application fields.",
        position=10,
    )
    for index, question in enumerate(starter.questions, start=1):
        options = [{"code": code, "label": label} for code, label in question.options]
        ApplicationQuestion.objects.create(
            definition=definition,
            section=section,
            key=question.key,
            field_type=question.field_type,
            label=question.label,
            position=index * 10,
            required=question.required,
            options=options,
            maximum_choices=(
                len(options) if question.field_type == "multiple_choice" else None
            ),
            source_binding=question.source_binding,
            purpose=question.purpose,
            classification=question.classification,
            applicant_writable=question.applicant_writable,
            retention_policy_code=starter.retention_policy_code,
        )
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.DEFINITION_CREATED,
        capability_code="applications.manage_definitions",
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=definition.aggregate_version,
        definition=definition,
        target_id=definition.id,
        changed_fields=("definition", "sections", "questions"),
    )


@transaction.atomic
def configure_definition(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
    expected_version: int,
    name: str,
    description: str,
    purpose: str,
    classification: str,
    eligibility_kind: str,
    maximum_submissions: int,
    opens_at: datetime,
    closes_at: datetime,
    applicant_edit_until: datetime,
    minimum_age: int,
    audience_policy_code: str,
    retention_policy_code: str,
    age_policy_code: str,
    owner_department_ids: Sequence[UUID],
    reviewer_role_bundle_ids: Sequence[UUID],
    reviewer_account_ids: Sequence[UUID],
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> ApplicationCommandResult:
    """Configure definition.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    definition_id : UUID
        The identifier of the definition.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    name : str
        The human-readable name.
    description : str
        The human-readable description.
    purpose : str
        The documented purpose of the operation.
    classification : str
        The closed data-classification code.
    eligibility_kind : str
        The closed eligibility kind discriminator defined by the domain catalog.
    maximum_submissions : int
        The maximum submissions applied within the audited domain transition.
    opens_at : datetime
        The time at which the window opens.
    closes_at : datetime
        The time at which the window closes.
    applicant_edit_until : datetime
        The timezone-aware boundary for applicant edit until.
    minimum_age : int
        The minimum age applied within the audited domain transition.
    audience_policy_code : str
        The stable audience policy code from the relevant closed catalog.
    retention_policy_code : str
        The stable retention policy code from the relevant closed catalog.
    age_policy_code : str
        The stable age policy code from the relevant closed catalog.
    owner_department_ids : Sequence[UUID]
        The selected owner department identifiers.
    reviewer_role_bundle_ids : Sequence[UUID]
        The selected reviewer role bundle identifiers.
    reviewer_account_ids : Sequence[UUID]
        The selected reviewer account identifiers.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.

    Returns
    -------
    ApplicationCommandResult
        The application command result.

    Raises
    ------
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    ApplicationUnavailable
        If the scoped target does not exist or cannot be disclosed.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    actor, edition = _edition_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.manage_definitions",
    )
    request_digest = _digest(
        {
            "operation": "definition.configure",
            "definition_id": definition_id,
            "expected_version": expected_version,
            "name": name,
            "description": description,
            "purpose": purpose,
            "classification": classification,
            "eligibility_kind": eligibility_kind,
            "maximum_submissions": maximum_submissions,
            "opens_at": opens_at,
            "closes_at": closes_at,
            "applicant_edit_until": applicant_edit_until,
            "minimum_age": minimum_age,
            "audience_policy_code": audience_policy_code,
            "retention_policy_code": retention_policy_code,
            "age_policy_code": age_policy_code,
            "owner_department_ids": owner_department_ids,
            "reviewer_role_bundle_ids": reviewer_role_bundle_ids,
            "reviewer_account_ids": reviewer_account_ids,
            "reason": reason,
        }
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    if not profile_allows_application_eligibility(
        edition.adoption_profile_code,
        edition.adoption_profile_version,
        eligibility_kind,
    ):
        raise ValidationError(
            {
                "eligibility_kind": (
                    "Choose an eligibility provider admitted by this edition."
                )
            },
            code="application_eligibility_provider_unavailable",
        )
    definition = _locked_definition(
        organization_id=organization_id,
        edition_id=edition_id,
        definition_id=definition_id,
    )
    _check_version(definition.aggregate_version, expected_version)
    if definition.status != ApplicationDefinitionStatus.DRAFT:
        raise ApplicationStateConflict
    definition.classification = classification
    if (
        not reason.strip()
        or len(owner_department_ids) > 32
        or len(reviewer_role_bundle_ids) > 32
        or len(reviewer_account_ids) > 32
    ):
        raise ValidationError(
            "Configuration evidence and assignment lists must be bounded."
        )
    from maru.authorization.models import RoleBundle  # noqa: PLC0415
    from maru.workforce.models import Department  # noqa: PLC0415

    departments = tuple(
        Department.objects.filter(
            id__in=owner_department_ids,
            organization_id=organization_id,
            edition_id=edition_id,
            retired_at__isnull=True,
        ).order_by("id")
    )
    roles = tuple(
        RoleBundle.objects.filter(
            id__in=reviewer_role_bundle_ids, organization_id=organization_id
        ).order_by("id")
    )
    if any(
        not profile_allows_application_reviewer_role(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
            role.capability_codes,
            sensitive=definition.is_sensitive,
        )
        for role in roles
    ):
        raise ValidationError(
            {
                "reviewer_role_bundle_ids": ValidationError(
                    (
                        "Choose an immutable reviewer role whose complete capability "
                        "set is admitted by this edition."
                    ),
                    code="application_reviewer_role_unavailable",
                )
            }
        )
    people = tuple(
        Account.objects.filter(
            id__in=reviewer_account_ids,
            is_active=True,
            account_kind=Account.Kind.PERSON,
        ).order_by("id")
    )
    if (
        len(departments) != len(set(owner_department_ids))
        or len(roles) != len(set(reviewer_role_bundle_ids))
        or len(people) != len(set(reviewer_account_ids))
    ):
        raise ApplicationUnavailable
    definition.name = name
    definition.description = description
    definition.purpose = purpose
    definition.eligibility_kind = eligibility_kind
    definition.max_submissions_per_person = maximum_submissions
    definition.opens_at = opens_at
    definition.closes_at = closes_at
    definition.applicant_edit_until = applicant_edit_until
    definition.minimum_age = minimum_age
    definition.audience_policy_code = audience_policy_code
    definition.retention_policy_code = retention_policy_code
    definition.age_policy_code = age_policy_code
    definition.aggregate_version += 1
    definition.save()
    definition.owner_department_links.all().delete()
    definition.reviewer_roles.all().delete()
    definition.reviewer_people.all().delete()
    for department in departments:
        ApplicationOwnerDepartment.objects.create(
            definition=definition, department=department
        )
    for role in roles:
        ApplicationReviewerRole.objects.create(definition=definition, role_bundle=role)
    for person in people:
        ApplicationReviewerPerson.objects.create(definition=definition, account=person)
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.DEFINITION_CONFIGURED,
        capability_code="applications.manage_definitions",
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=definition.aggregate_version,
        definition=definition,
        target_id=definition.id,
        changed_fields=(
            "definition",
            "owner_departments",
            "reviewer_roles",
            "reviewer_people",
        ),
    )


@transaction.atomic
def add_section(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
    expected_version: int,
    key: str,
    title: str,
    help_text: str,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> ApplicationCommandResult:
    """Add section.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    definition_id : UUID
        The identifier of the definition.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    key : str
        The stable lookup key.
    title : str
        The human-readable title.
    help_text : str
        The explanatory text shown to the user.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.

    Returns
    -------
    ApplicationCommandResult
        The application command result.

    Raises
    ------
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    """
    actor, _ = _edition_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.manage_definitions",
    )
    request_digest = _digest(
        {
            "operation": "section.add",
            "definition_id": definition_id,
            "expected_version": expected_version,
            "key": key,
            "title": title,
            "help_text": help_text,
            "reason": reason,
        }
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    definition = _locked_definition(
        organization_id=organization_id,
        edition_id=edition_id,
        definition_id=definition_id,
    )
    _check_version(definition.aggregate_version, expected_version)
    if (
        definition.status != ApplicationDefinitionStatus.DRAFT
        or definition.sections.count() >= MAX_SECTIONS
        or not reason.strip()
    ):
        raise ApplicationStateConflict
    position = (definition.sections.aggregate(value=Max("position"))["value"] or 0) + 10
    section = ApplicationSection.objects.create(
        definition=definition,
        key=key,
        title=title,
        help_text=help_text,
        position=position,
    )
    definition.aggregate_version += 1
    definition.save(update_fields=("aggregate_version", "updated_at"))
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.SECTION_ADDED,
        capability_code="applications.manage_definitions",
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=definition.aggregate_version,
        definition=definition,
        target_id=section.id,
        changed_fields=("sections",),
    )


@transaction.atomic
def add_question(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
    section_id: UUID,
    expected_version: int,
    key: str,
    field_type: str,
    label: str,
    help_text: str,
    required: bool,
    options: list[dict[str, str]],
    minimum_length: int | None,
    maximum_length: int | None,
    minimum_value: Decimal | None,
    maximum_value: Decimal | None,
    maximum_choices: int | None,
    reference_kind: str,
    condition: dict[str, object],
    purpose: str,
    classification: str,
    applicant_visible: bool,
    applicant_writable: bool,
    staff_visible: bool,
    staff_writable: bool,
    reviewer_visible: bool,
    public_after_approval: bool,
    api_projection: bool,
    retention_policy_code: str,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> ApplicationCommandResult:
    """Add question.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    definition_id : UUID
        The identifier of the definition.
    section_id : UUID
        The identifier of the section.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    key : str
        The stable lookup key.
    field_type : str
        The closed field-type code.
    label : str
        The human-readable label.
    help_text : str
        The explanatory text shown to the user.
    required : bool
        Whether the input is required.
    options : list[dict[str, str]]
        The permitted operation options.
    minimum_length : int | None
        The minimum length applied within the audited domain transition.
    maximum_length : int | None
        The maximum length applied within the audited domain transition.
    minimum_value : Decimal | None
        The minimum value applied within the audited domain transition.
    maximum_value : Decimal | None
        The maximum value applied within the audited domain transition.
    maximum_choices : int | None
        The authorized maximum choices presented for validated selection.
    reference_kind : str
        The closed reference kind discriminator defined by the domain catalog.
    condition : dict[str, object]
        The configured condition evaluated against the submitted answer.
    purpose : str
        The documented purpose of the operation.
    classification : str
        The closed data-classification code.
    applicant_visible : bool
        The applicant visible applied within the audited domain transition.
    applicant_writable : bool
        The applicant writable applied within the audited domain transition.
    staff_visible : bool
        The staff visible applied within the audited domain transition.
    staff_writable : bool
        The staff writable applied within the audited domain transition.
    reviewer_visible : bool
        The reviewer visible applied within the audited domain transition.
    public_after_approval : bool
        The public after approval applied within the audited domain transition.
    api_projection : bool
        The api projection applied within the audited domain transition.
    retention_policy_code : str
        The stable retention policy code from the relevant closed catalog.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.

    Returns
    -------
    ApplicationCommandResult
        The application command result.

    Raises
    ------
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    """
    actor, _ = _edition_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.manage_definitions",
    )
    request_digest = _digest(
        {
            "operation": "question.add",
            "definition_id": definition_id,
            "section_id": section_id,
            "expected_version": expected_version,
            "key": key,
            "field_type": field_type,
            "label": label,
            "help_text": help_text,
            "required": required,
            "options": options,
            "minimum_length": minimum_length,
            "maximum_length": maximum_length,
            "minimum_value": minimum_value,
            "maximum_value": maximum_value,
            "maximum_choices": maximum_choices,
            "reference_kind": reference_kind,
            "condition": condition,
            "purpose": purpose,
            "classification": classification,
            "applicant_visible": applicant_visible,
            "applicant_writable": applicant_writable,
            "staff_visible": staff_visible,
            "staff_writable": staff_writable,
            "reviewer_visible": reviewer_visible,
            "public_after_approval": public_after_approval,
            "api_projection": api_projection,
            "retention_policy_code": retention_policy_code,
            "reason": reason,
        }
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    definition = _locked_definition(
        organization_id=organization_id,
        edition_id=edition_id,
        definition_id=definition_id,
    )
    _check_version(definition.aggregate_version, expected_version)
    section = ApplicationSection.objects.filter(
        id=section_id, definition=definition
    ).first()
    if (
        definition.status != ApplicationDefinitionStatus.DRAFT
        or section is None
        or definition.questions.count() >= MAX_QUESTIONS
        or not reason.strip()
    ):
        raise ApplicationStateConflict
    position = (section.questions.aggregate(value=Max("position"))["value"] or 0) + 10
    question = ApplicationQuestion.objects.create(
        definition=definition,
        section=section,
        key=key,
        field_type=field_type,
        label=label,
        help_text=help_text,
        position=position,
        required=required,
        options=options,
        minimum_length=minimum_length,
        maximum_length=maximum_length,
        minimum_value=minimum_value,
        maximum_value=maximum_value,
        maximum_choices=maximum_choices,
        reference_kind=reference_kind,
        condition=condition,
        purpose=purpose,
        classification=classification,
        applicant_visible=applicant_visible,
        applicant_writable=applicant_writable,
        staff_visible=staff_visible,
        staff_writable=staff_writable,
        reviewer_visible=reviewer_visible,
        public_after_approval=public_after_approval,
        api_projection=api_projection,
        retention_policy_code=retention_policy_code,
    )
    definition.aggregate_version += 1
    definition.save(update_fields=("aggregate_version", "updated_at"))
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.QUESTION_ADDED,
        capability_code="applications.manage_definitions",
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=definition.aggregate_version,
        definition=definition,
        target_id=question.id,
        changed_fields=("questions",),
    )


def _validate_definition_activation(definition: ApplicationDefinition) -> None:
    questions = tuple(
        definition.questions.select_related("section").order_by(
            "section__position", "position", "id"
        )
    )
    edition = definition.edition
    if not profile_allows_application_target(
        edition.adoption_profile_code,
        edition.adoption_profile_version,
        definition.target_adapter_kind,
    ):
        raise ValidationError(
            "The accepted-target adapter is unavailable for this edition.",
            code="application_target_adapter_unavailable",
        )
    if not profile_allows_application_eligibility(
        edition.adoption_profile_code,
        edition.adoption_profile_version,
        definition.eligibility_kind,
    ):
        raise ValidationError(
            "The definition eligibility provider is unavailable for this edition.",
            code="application_eligibility_provider_unavailable",
        )
    if any(
        not profile_allows_application_source(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
            question.source_binding,
        )
        for question in questions
    ):
        raise ValidationError(
            "A definition question source is unavailable for this edition.",
            code="application_source_provider_unavailable",
        )
    reviewer_role_links = tuple(
        definition.reviewer_roles.select_related("role_bundle").order_by(
            "role_bundle_id",
            "id",
        )
    )
    if any(
        not profile_allows_application_reviewer_role(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
            link.role_bundle.capability_codes,
            sensitive=definition.is_sensitive,
        )
        for link in reviewer_role_links
    ):
        raise ValidationError(
            "A reviewer role is unavailable for this edition's exact profile.",
            code="application_reviewer_role_unavailable",
        )
    if not definition.owner_department_links.exists():
        raise ValidationError(
            "Assign at least one owning Department.", code="application_owner_required"
        )
    if not (definition.reviewer_roles.exists() or definition.reviewer_people.exists()):
        raise ValidationError(
            "Assign at least one reviewer queue.", code="application_reviewer_required"
        )
    if not definition.sections.exists() or not questions:
        raise ValidationError(
            "An active application requires a section and question.",
            code="application_definition_empty",
        )
    if definition.is_sensitive and (
        not definition.retention_policy_code or not definition.audience_policy_code
    ):
        raise ValidationError(
            "Sensitive applications require explicit audience and retention policies.",
            code="explicit_sensitive_application_policy_required",
        )
    question_keys = {question.key for question in questions}
    classification_rank: dict[str, int] = {
        ApplicationClassification.INTERNAL: 1,
        ApplicationClassification.PERSONAL: 2,
        ApplicationClassification.RESTRICTED: 3,
        ApplicationClassification.SECURITY_CRITICAL: 4,
    }
    graph: dict[str, str] = {}
    for question in questions:
        if (
            classification_rank[question.classification]
            > classification_rank[definition.classification]
        ):
            raise ValidationError(
                "A question cannot exceed its definition classification.",
                code="application_question_classification_exceeds_definition",
            )
        if question.required and not question.applicant_visible:
            raise ValidationError(
                "Required questions must be applicant-visible.",
                code="required_application_question_hidden",
            )
        if question.classification in {
            ApplicationClassification.RESTRICTED,
            ApplicationClassification.SECURITY_CRITICAL,
        } and not (question.retention_policy_code or definition.retention_policy_code):
            raise ValidationError(
                "Sensitive questions require explicit retention.",
                code="sensitive_question_retention_required",
            )
        if question.condition:
            dependency = str(question.condition["question_key"])
            if dependency not in question_keys or dependency == question.key:
                raise ValidationError(
                    "Question conditions must reference another definition question.",
                    code="invalid_application_condition",
                )
            graph[question.key] = dependency
    for start in graph:
        seen: set[str] = set()
        current = start
        while current in graph:
            if current in seen:
                raise ValidationError(
                    "Question conditions cannot contain a cycle.",
                    code="cyclic_application_condition",
                )
            seen.add(current)
            current = graph[current]


@transaction.atomic
def activate_definition(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> ApplicationCommandResult:
    """Activate definition.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    definition_id : UUID
        The identifier of the definition.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.

    Returns
    -------
    ApplicationCommandResult
        The application command result.

    Raises
    ------
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    """
    actor, _ = _edition_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.manage_definitions",
    )
    request_digest = _digest(
        {
            "operation": "definition.activate",
            "definition_id": definition_id,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    definition = _locked_definition(
        organization_id=organization_id,
        edition_id=edition_id,
        definition_id=definition_id,
    )
    _check_version(definition.aggregate_version, expected_version)
    if (
        definition.status != ApplicationDefinitionStatus.DRAFT
        or not reason.strip()
        or ApplicationDefinition.objects.filter(
            edition_id=edition_id,
            code=definition.code,
            status=ApplicationDefinitionStatus.ACTIVE,
        )
        .exclude(id=definition.id)
        .exists()
    ):
        raise ApplicationStateConflict
    _validate_definition_activation(definition)
    now = timezone.now()
    definition.status = ApplicationDefinitionStatus.ACTIVE
    definition.activated_at = now
    definition.activated_by = actor
    definition.aggregate_version += 1
    definition.save()
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.DEFINITION_ACTIVATED,
        capability_code="applications.manage_definitions",
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=definition.aggregate_version,
        definition=definition,
        target_id=definition.id,
        changed_fields=("status", "activated_at"),
    )


@transaction.atomic
def retire_definition(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> ApplicationCommandResult:
    """Retire definition.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    definition_id : UUID
        The identifier of the definition.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.

    Returns
    -------
    ApplicationCommandResult
        The application command result.

    Raises
    ------
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    """
    actor, _ = _edition_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.manage_definitions",
    )
    request_digest = _digest(
        {
            "operation": "definition.retire",
            "definition_id": definition_id,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    definition = _locked_definition(
        organization_id=organization_id,
        edition_id=edition_id,
        definition_id=definition_id,
    )
    _check_version(definition.aggregate_version, expected_version)
    if definition.status != ApplicationDefinitionStatus.ACTIVE or not reason.strip():
        raise ApplicationStateConflict
    now = timezone.now()
    definition.status = ApplicationDefinitionStatus.RETIRED
    definition.retired_at = now
    definition.retired_by = actor
    definition.aggregate_version += 1
    definition.save()
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.DEFINITION_RETIRED,
        capability_code="applications.manage_definitions",
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=definition.aggregate_version,
        definition=definition,
        target_id=definition.id,
        changed_fields=("status", "retired_at"),
    )


@transaction.atomic
def create_successor_definition(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> ApplicationCommandResult:
    """Create successor definition.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    definition_id : UUID
        The identifier of the definition.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.

    Returns
    -------
    ApplicationCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    """
    actor, _ = _edition_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.manage_definitions",
    )
    request_digest = _digest(
        {
            "operation": "definition.successor",
            "definition_id": definition_id,
            "reason": reason,
        }
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    source = _locked_definition(
        organization_id=organization_id,
        edition_id=edition_id,
        definition_id=definition_id,
    )
    if source.status == ApplicationDefinitionStatus.DRAFT or not reason.strip():
        raise ApplicationStateConflict
    rows = ApplicationDefinition.objects.select_for_update().filter(
        edition_id=edition_id, code=source.code
    )
    next_version = (rows.aggregate(value=Max("version"))["value"] or 0) + 1
    if rows.filter(status=ApplicationDefinitionStatus.DRAFT).exists():
        raise ApplicationStateConflict
    successor = ApplicationDefinition.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        code=source.code,
        version=next_version,
        target_adapter_kind=source.target_adapter_kind,
        name=source.name,
        description=source.description,
        purpose=source.purpose,
        classification=source.classification,
        eligibility_kind=source.eligibility_kind,
        max_submissions_per_person=source.max_submissions_per_person,
        opens_at=source.opens_at,
        closes_at=source.closes_at,
        applicant_edit_until=source.applicant_edit_until,
        minimum_age=source.minimum_age,
        audience_policy_code=source.audience_policy_code,
        retention_policy_code=source.retention_policy_code,
        age_policy_code=source.age_policy_code,
        created_by=actor,
    )
    section_map: dict[UUID, ApplicationSection] = {}
    for section in source.sections.order_by("position", "id"):
        section_map[section.id] = ApplicationSection.objects.create(
            definition=successor,
            key=section.key,
            title=section.title,
            help_text=section.help_text,
            position=section.position,
        )
    for question in source.questions.order_by("section__position", "position", "id"):
        ApplicationQuestion.objects.create(
            definition=successor,
            section=section_map[question.section_id],
            key=question.key,
            field_type=question.field_type,
            label=question.label,
            help_text=question.help_text,
            position=question.position,
            required=question.required,
            options=question.options,
            minimum_length=question.minimum_length,
            maximum_length=question.maximum_length,
            minimum_value=question.minimum_value,
            maximum_value=question.maximum_value,
            maximum_choices=question.maximum_choices,
            reference_kind=question.reference_kind,
            source_binding=question.source_binding,
            condition=question.condition,
            purpose=question.purpose,
            classification=question.classification,
            applicant_visible=question.applicant_visible,
            applicant_writable=question.applicant_writable,
            staff_visible=question.staff_visible,
            staff_writable=question.staff_writable,
            reviewer_visible=question.reviewer_visible,
            public_after_approval=question.public_after_approval,
            api_projection=question.api_projection,
            retention_policy_code=question.retention_policy_code,
        )
    for owner_link in source.owner_department_links.select_related("department"):
        ApplicationOwnerDepartment.objects.create(
            definition=successor, department=owner_link.department
        )
    for reviewer_role_link in source.reviewer_roles.select_related("role_bundle"):
        ApplicationReviewerRole.objects.create(
            definition=successor, role_bundle=reviewer_role_link.role_bundle
        )
    for reviewer_person_link in source.reviewer_people.select_related("account"):
        ApplicationReviewerPerson.objects.create(
            definition=successor, account=reviewer_person_link.account
        )
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.SUCCESSOR_CREATED,
        capability_code="applications.manage_definitions",
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=successor.aggregate_version,
        definition=successor,
        target_id=successor.id,
        changed_fields=("definition", "sections", "questions", "reviewers"),
    )


@transaction.atomic
def start_submission(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
) -> ApplicationCommandResult:
    """Start submission.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    definition_id : UUID
        The identifier of the definition.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    ApplicationCommandResult
        The application command result.

    Raises
    ------
    ApplicationEligibilityDenied
        If the subject does not satisfy the configured eligibility policy.
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    ApplicationUnavailable
        If the scoped target does not exist or cannot be disclosed.
    """
    actor, _ = _self_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.apply_self",
    )
    request_digest = _digest(
        {"operation": "submission.start", "definition_id": definition_id}
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    definition = _locked_definition(
        organization_id=organization_id,
        edition_id=edition_id,
        definition_id=definition_id,
    )
    evaluated_at = now or timezone.now()
    if (
        definition.status != ApplicationDefinitionStatus.ACTIVE
        or not definition.opens_at <= evaluated_at < definition.closes_at
    ):
        raise ApplicationUnavailable
    if not applicant_is_eligible(definition=definition, account=actor, at=evaluated_at):
        raise ApplicationEligibilityDenied
    existing = ApplicationSubmission.objects.select_for_update().filter(
        definition=definition, account=actor
    )
    count = existing.count()
    if count >= definition.max_submissions_per_person:
        raise ApplicationStateConflict
    submission = ApplicationSubmission.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        definition=definition,
        account=actor,
        ordinal=count + 1,
    )
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.SUBMISSION_STARTED,
        capability_code="applications.apply_self",
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=submission.aggregate_version,
        definition=definition,
        submission=submission,
        target_id=submission.id,
        changed_fields=("state",),
    )


def _locked_owned_submission(
    *, actor: Account, organization_id: UUID, edition_id: UUID, submission_id: UUID
) -> ApplicationSubmission:
    submission = (
        ApplicationSubmission.objects.select_for_update()
        .select_related("definition", "account")
        .filter(
            id=submission_id,
            organization_id=organization_id,
            edition_id=edition_id,
            account_id=actor.id,
            definition__target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .first()
    )
    if submission is None:
        raise ApplicationUnavailable
    return submission


@transaction.atomic
def append_answer_revision(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
    question_id: UUID,
    expected_version: int,
    value: object,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
) -> ApplicationCommandResult:
    """Append answer revision.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    submission_id : UUID
        The identifier of the submission.
    question_id : UUID
        The identifier of the question.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    value : object
        The untrusted value to normalize against the documented contract.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    ApplicationCommandResult
        The application command result.

    Raises
    ------
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    ApplicationUnavailable
        If the scoped target does not exist or cannot be disclosed.
    """
    actor, _ = _self_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.apply_self",
    )
    request_digest = _digest(
        {
            "operation": "answer.revise",
            "submission_id": submission_id,
            "question_id": question_id,
            "expected_version": expected_version,
            "value": value,
        }
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    submission = _locked_owned_submission(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        submission_id=submission_id,
    )
    _check_version(submission.aggregate_version, expected_version)
    evaluated_at = now or timezone.now()
    if (
        submission.state
        not in {ApplicationState.DRAFT, ApplicationState.CHANGES_REQUESTED}
        or evaluated_at > submission.definition.applicant_edit_until
    ):
        raise ApplicationStateConflict
    question = ApplicationQuestion.objects.filter(
        id=question_id,
        definition=submission.definition,
        applicant_visible=True,
        applicant_writable=True,
    ).first()
    if question is None:
        raise ApplicationUnavailable
    normalized = normalize_answer_value(question=question, account=actor, value=value)
    sequence = (
        ApplicationAnswerRevision.objects.select_for_update()
        .filter(submission=submission, question=question)
        .aggregate(value=Max("sequence"))["value"]
        or 0
    ) + 1
    revision = ApplicationAnswerRevision.objects.create(
        submission=submission,
        question=question,
        sequence=sequence,
        question_key=question.key,
        question_type=question.field_type,
        classification=question.classification,
        value=normalized,
        source=AnswerSource.APPLICANT,
        actor=actor,
    )
    submission.aggregate_version += 1
    submission.save(update_fields=("aggregate_version", "updated_at"))
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.ANSWER_REVISED,
        capability_code="applications.apply_self",
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=submission.aggregate_version,
        definition=submission.definition,
        submission=submission,
        target_id=revision.id,
        changed_fields=("answers",),
    )


def _latest_answers(submission: ApplicationSubmission) -> dict[str, object]:
    latest: dict[str, object] = {}
    revisions = submission.answer_revisions.order_by("question_key", "-sequence", "-id")
    for revision in revisions:
        if revision.question_key not in latest:
            latest[revision.question_key] = revision.value
    return latest


@transaction.atomic
def submit_application(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
    expected_version: int,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
) -> ApplicationCommandResult:
    """Submit application.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    submission_id : UUID
        The identifier of the submission.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    ApplicationCommandResult
        The application command result.

    Raises
    ------
    ApplicationEligibilityDenied
        If the subject does not satisfy the configured eligibility policy.
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    actor, _ = _self_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.apply_self",
    )
    request_digest = _digest(
        {
            "operation": "application.submit",
            "submission_id": submission_id,
            "expected_version": expected_version,
        }
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    submission = _locked_owned_submission(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        submission_id=submission_id,
    )
    _check_version(submission.aggregate_version, expected_version)
    evaluated_at = now or timezone.now()
    if (
        submission.state
        not in {ApplicationState.DRAFT, ApplicationState.CHANGES_REQUESTED}
        or evaluated_at > submission.definition.applicant_edit_until
        or evaluated_at >= submission.definition.closes_at
    ):
        raise ApplicationStateConflict
    if not applicant_is_eligible(
        definition=submission.definition, account=actor, at=evaluated_at
    ):
        raise ApplicationEligibilityDenied
    answers = _latest_answers(submission)
    for question in submission.definition.questions.filter(
        applicant_visible=True
    ).order_by("section__position", "position", "id"):
        if question.source_binding:
            sourced = source_bound_value(question=question, account=actor)
            normalized = normalize_answer_value(
                question=question, account=actor, value=sourced
            )
            previous = answers.get(question.key)
            if previous != normalized:
                sequence = (
                    ApplicationAnswerRevision.objects.select_for_update()
                    .filter(submission=submission, question=question)
                    .aggregate(value=Max("sequence"))["value"]
                    or 0
                ) + 1
                ApplicationAnswerRevision.objects.create(
                    submission=submission,
                    question=question,
                    sequence=sequence,
                    question_key=question.key,
                    question_type=question.field_type,
                    classification=question.classification,
                    value=normalized,
                    source=AnswerSource.SYSTEM_SOURCE,
                    actor=actor,
                )
                answers[question.key] = normalized
        if (
            question.required
            and condition_matches(question.condition, answers)
            and (answers.get(question.key) is None or answers.get(question.key) == "")
        ):
            raise ValidationError(
                {question.key: "This application field is required."},
                code="required_application_answer_missing",
            )
        if (
            question.required
            and condition_matches(question.condition, answers)
            and isinstance(answers.get(question.key), (list, dict))
            and not answers[question.key]
        ):
            raise ValidationError(
                {question.key: "This application field is required."},
                code="required_application_answer_missing",
            )
    if submission.submitted_at is None:
        submission.submitted_at = evaluated_at
    submission.state = ApplicationState.SUBMITTED
    submission.aggregate_version += 1
    submission.save()
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.APPLICATION_SUBMITTED,
        capability_code="applications.apply_self",
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=submission.aggregate_version,
        definition=submission.definition,
        submission=submission,
        target_id=submission.id,
        changed_fields=("state", "submitted_at"),
    )


def _reviewer_basis(
    *, actor: Account, definition: ApplicationDefinition, evaluated_at: datetime
) -> tuple[str, RoleBundle | None]:
    if definition.reviewer_people.filter(account_id=actor.id).exists():
        return ReviewerBasis.NAMED_PERSON, None
    edition = definition.edition
    role_bundle_ids = frozenset(
        link.role_bundle_id
        for link in definition.reviewer_roles.select_related("role_bundle").order_by(
            "role_bundle_id",
            "id",
        )
        if profile_allows_application_reviewer_role(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
            link.role_bundle.capability_codes,
            sensitive=definition.is_sensitive,
        )
    )
    if not role_bundle_ids:
        raise ApplicationAuthorizationDenied
    owner_department_ids = tuple(
        definition.owner_department_links.values_list("department_id", flat=True)
    )
    scope = Q(
        edition__isnull=True, department__isnull=True, resource_binding__isnull=True
    ) | Q(
        edition_id=definition.edition_id,
        department__isnull=True,
        resource_binding__isnull=True,
    )
    if owner_department_ids:
        scope |= Q(
            edition_id=definition.edition_id,
            department_id__in=owner_department_ids,
            resource_binding__isnull=True,
        )
    candidates = tuple(
        RoleAssignment.objects.filter(
            scope,
            organization_id=definition.organization_id,
            principal_id=actor.id,
            role_bundle_id__in=role_bundle_ids,
        )
        .select_related("role_bundle")
        .order_by("role_bundle_id", "id")
    )
    current_ids = current_role_assignment_ids(
        assignment_ids={assignment.id for assignment in candidates},
        at=evaluated_at,
    )
    for assignment in candidates:
        if assignment.id in current_ids:
            return ReviewerBasis.IMMUTABLE_ROLE, assignment.role_bundle
    raise ApplicationAuthorizationDenied


@transaction.atomic
def record_review_decision(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
    expected_version: int,
    decision: str,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
) -> ApplicationCommandResult:
    """Record review decision.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    submission_id : UUID
        The identifier of the submission.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    decision : str
        The requested governed decision.
    reason : str
        The operator-supplied reason for the operation.
    retry_key : UUID
        The stable key used to retry the operation safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    source_channel : str
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    ApplicationCommandResult
        The application command result.

    Raises
    ------
    ApplicationStateConflict
        If the target lifecycle state does not permit the transition.
    ApplicationUnavailable
        If the scoped target does not exist or cannot be disclosed.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    actor, edition = _edition_target(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.review",
    )
    request_digest = _digest(
        {
            "operation": "review.decide",
            "submission_id": submission_id,
            "expected_version": expected_version,
            "decision": decision,
            "reason": reason,
        }
    )
    replay = _replay(
        actor=actor,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=request_digest,
    )
    if replay is not None:
        return replay
    submission = (
        ApplicationSubmission.objects.select_for_update()
        .select_related("definition")
        .filter(
            id=submission_id,
            organization_id=organization_id,
            edition_id=edition_id,
            definition__target_adapter_kind__in=LEGACY_APPLICATION_TARGET_KINDS,
        )
        .first()
    )
    if submission is None:
        raise ApplicationUnavailable
    _check_version(submission.aggregate_version, expected_version)
    evaluated_at = now or timezone.now()
    if submission.definition.is_sensitive:
        _edition_target(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="applications.review_sensitive",
        )
    basis, role_bundle = _reviewer_basis(
        actor=actor, definition=submission.definition, evaluated_at=evaluated_at
    )
    if not reason.strip():
        raise ValidationError({"reason": "Record an accountable review reason."})
    transitions = {
        ReviewDecisionKind.START_REVIEW: (
            {ApplicationState.SUBMITTED},
            ApplicationState.UNDER_REVIEW,
        ),
        ReviewDecisionKind.REQUEST_CHANGES: (
            {ApplicationState.SUBMITTED, ApplicationState.UNDER_REVIEW},
            ApplicationState.CHANGES_REQUESTED,
        ),
        ReviewDecisionKind.ACCEPT: (
            {
                ApplicationState.SUBMITTED,
                ApplicationState.UNDER_REVIEW,
                ApplicationState.CHANGES_REQUESTED,
            },
            ApplicationState.ACCEPTED,
        ),
        ReviewDecisionKind.REJECT: (
            {
                ApplicationState.SUBMITTED,
                ApplicationState.UNDER_REVIEW,
                ApplicationState.CHANGES_REQUESTED,
            },
            ApplicationState.REJECTED,
        ),
    }
    transition = transitions.get(cast("ReviewDecisionKind", decision))
    if transition is None or submission.state not in transition[0]:
        raise ApplicationStateConflict
    from_state = submission.state
    to_state = transition[1]
    if to_state == ApplicationState.ACCEPTED and not (
        profile_allows_application_target(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
            submission.definition.target_adapter_kind,
        )
    ):
        raise ValidationError(
            "The accepted-target adapter is unavailable for this edition.",
            code="application_target_adapter_unavailable",
        )
    submission.state = to_state
    if to_state in {ApplicationState.ACCEPTED, ApplicationState.REJECTED}:
        submission.decided_at = evaluated_at
    submission.aggregate_version += 1
    submission.save()
    sequence = (
        ApplicationReviewDecision.objects.select_for_update()
        .filter(submission=submission)
        .aggregate(value=Max("sequence"))["value"]
        or 0
    ) + 1
    review = ApplicationReviewDecision.objects.create(
        submission=submission,
        sequence=sequence,
        decision=decision,
        from_state=from_state,
        to_state=to_state,
        reviewer=actor,
        reviewer_basis=basis,
        reviewer_role_bundle=role_bundle,
        reason=reason.strip(),
    )
    target_id: UUID = review.id
    changed_fields: tuple[str, ...] = ("state", "review_history")
    if to_state == ApplicationState.ACCEPTED:
        target = ApplicationTargetRecord.objects.create(
            submission=submission,
            adapter_kind=submission.definition.target_adapter_kind,
            created_by=actor,
        )
        target_id = target.id
        changed_fields = ("state", "review_history", "typed_target")
    return _record_evidence(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        action=ApplicationCommandReceipt.Action.REVIEW_DECIDED,
        capability_code=(
            "applications.review_sensitive"
            if submission.definition.is_sensitive
            else "applications.review"
        ),
        request_digest=request_digest,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        resulting_version=submission.aggregate_version,
        definition=submission.definition,
        submission=submission,
        target_id=target_id,
        changed_fields=changed_fields,
    )
