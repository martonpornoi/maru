"""Governed profile-extension value commands and bounded current projections."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Value

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.policy import (
    PolicyDecision,
    decide,
    resolve_department_target,
    resolve_edition_target,
    resolve_owned_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import DomainEvent, OutboxMessage
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.identity.models import Account
from maru.registration.models import (
    AttendeeRegistrationProfile,
    ProfileExtensionAudience,
    ProfileExtensionReviewStatus,
    ProfileExtensionStatus,
    ProfileExtensionValueWriterKind,
    ProfileExtensionWriter,
    Registration,
    RegistrationProfileExtensionField,
    RegistrationProfileExtensionValueCommandReceipt,
    RegistrationProfileExtensionValueControl,
    RegistrationProfileExtensionValueRevision,
)
from maru.registration.profile_policy import DIRECTORY_CONSENT_VERSION
from maru.registration.services import (
    _audit_record,
    _normalize_profile_extension_value,
    _require_decision,
)
from maru.registration.setup_content import canonical_digest

MANAGE_SELF_PROFILE = "registration.manage_self_profile"
VIEW_SELF_PROFILE = "registration.view_self_profile"
VIEW_PROFILE_EXTENSIONS = "registration.view_profile_extensions"
UPDATE_PROFILE_EXTENSIONS = "registration.update_profile_extensions"
MAX_PROFILE_EXTENSION_FIELDS = 128
MAX_DIRECTORY_PROFILE_EXTENSION_VALUES = 4_096
MAX_PROFILE_EXTENSION_VALUE_BYTES = 16_384
MAX_STAFF_REASON_LENGTH = 500
_SOURCE_CHANNEL = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class ProfileExtensionValueError(Exception):
    """Signal profile extension value."""

    reason_code = "profile_extension_value_error"


class ProfileExtensionValueUnavailableError(ProfileExtensionValueError):
    """Signal profile extension value unavailable."""

    reason_code = "profile_extension_value_unavailable"


class ProfileExtensionValueSequenceConflictError(ProfileExtensionValueError):
    """Signal profile extension value sequence conflict."""

    reason_code = "profile_extension_value_sequence_conflict"


class ProfileExtensionValueRetryConflictError(ProfileExtensionValueError):
    """Signal profile extension value retry conflict."""

    reason_code = "profile_extension_value_retry_conflict"


class ProfileExtensionValueEvidenceConflictError(ProfileExtensionValueError):
    """Signal profile extension value evidence conflict."""

    reason_code = "profile_extension_value_evidence_conflict"


class ProfileExtensionValueLimitExceededError(ProfileExtensionValueError):
    """Signal profile extension value limit exceeded."""

    reason_code = "profile_extension_value_limit_exceeded"


@dataclass(frozen=True, slots=True)
class ProfileExtensionValueCommandResult:
    """Describe profile extension value command result.

    Attributes
    ----------
    registration_id
        The attendee registration identifier within the edition scope.
    field_id
        The field identifier within the requested scope.
    field_key
        The stable field key used to authenticate or deduplicate the operation.
    field_version
        The expected field version used to reject stale updates.
    revision_id
        The revision identifier within the requested scope.
    receipt_id
        The receipt identifier within the requested scope.
    result_sequence
        The expected result sequence used to reject stale updates.
    value
        The untrusted input to normalize, validate, or compare.
    writer_kind
        The closed writer kind discriminator defined by the domain catalog.
    source_channel
        The closed channel code identifying where the request originated.
    changed_at
        The timezone-aware timestamp for changed.
    replayed
        The replayed retained in this immutable projection.
    """

    registration_id: UUID
    field_id: UUID
    field_key: str
    field_version: int
    revision_id: UUID
    receipt_id: UUID
    result_sequence: int
    value: object
    writer_kind: str
    source_channel: str
    changed_at: datetime
    replayed: bool


@dataclass(frozen=True, slots=True)
class ProfileExtensionValueFieldProjection:
    """Describe profile extension value field projection.

    Attributes
    ----------
    field_id
        The field identifier within the requested scope.
    field_key
        The stable field key used to authenticate or deduplicate the operation.
    field_version
        The expected field version used to reject stale updates.
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
    audience_policy
        The closed audience policy governing validation or disclosure.
    audience_department_id
        The audience department identifier within the requested scope.
    required
        The required retained in this immutable projection.
    writer_policy
        The closed writer policy governing validation or disclosure.
    can_write
        The can write retained in this immutable projection.
    current_value
        The current value retained in this immutable projection.
    current_sequence
        The expected current sequence used to reject stale updates.
    updated_at
        The timezone-aware timestamp for updated.
    """

    field_id: UUID
    field_key: str
    field_version: int
    label: str
    help_text: str
    field_type: str
    options: tuple[str, ...]
    purpose: str
    classification: str
    audience_policy: str
    audience_department_id: UUID | None
    required: bool
    writer_policy: str
    can_write: bool
    current_value: object | None
    current_sequence: int
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProfileExtensionValueWorkspace:
    """Describe profile extension value workspace.

    Attributes
    ----------
    registration_id
        The attendee registration identifier within the edition scope.
    snapshot_digest
        The canonical digest used to verify snapshot.
    fields
        The canonical field names included in the operation.
    """

    registration_id: UUID
    snapshot_digest: str
    fields: tuple[ProfileExtensionValueFieldProjection, ...]


@dataclass(frozen=True, slots=True)
class DirectoryProfileExtensionProjection:
    """Describe directory profile extension projection.

    Attributes
    ----------
    field_id
        The field identifier within the requested scope.
    label
        The human-readable label shown to authorized readers.
    value
        The untrusted input to normalize, validate, or compare.
    audience_policy
        The closed audience policy governing validation or disclosure.
    """

    field_id: UUID
    label: str
    value: object
    audience_policy: str


def _strict_uuid(value: UUID | object, *, field: str) -> UUID:
    if type(value) is not UUID:
        raise ValidationError(
            {field: "Use one canonical UUID."},
            code="invalid_profile_extension_value_uuid",
        )
    return value


def _strict_sequence(value: int | object) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(
            {"expected_sequence": "Use a whole number of zero or greater."},
            code="invalid_profile_extension_value_sequence",
        )
    return value


def _strict_source_channel(value: str | object) -> str:
    if not isinstance(value, str) or not _SOURCE_CHANNEL.fullmatch(value):
        raise ValidationError(
            {"source_channel": "Use one registered source channel."},
            code="invalid_profile_extension_value_source",
        )
    return value


def _bounded_json(value: object) -> object:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValidationError(
            {"value": "Use one valid JSON value."},
            code="invalid_profile_extension_value_json",
        ) from error
    if len(encoded) > MAX_PROFILE_EXTENSION_VALUE_BYTES:
        raise ValidationError(
            {"value": ("The encoded profile value exceeds the 16 KiB command limit.")},
            code="profile_extension_value_too_large",
        )
    return value


def _reason(value: str | object) -> str:
    if not isinstance(value, str):
        raise ValidationError(
            {"reason": "Use text for the change reason."},
            code="invalid_profile_extension_value_reason",
        )
    normalized = value.strip()
    if len(normalized) > MAX_STAFF_REASON_LENGTH:
        raise ValidationError(
            {"reason": "Use no more than 500 characters."},
            code="profile_extension_value_reason_too_long",
        )
    return normalized


_REQUEST_DIGEST_SQL = """
SELECT encode(
    sha256(
        convert_to(
            jsonb_build_object(
                'actor_id', %s::uuid::text,
                'contract',
                    'maru.registration-profile-extension-value-command.v2',
                'edition_id', %s::uuid::text,
                'expected_sequence', %s::integer,
                'field_id', %s::uuid::text,
                'organization_id', %s::uuid::text,
                'reason', %s::text,
                'registration_id', %s::uuid::text,
                'source_channel', %s::text,
                'value', %s::jsonb
            )::text,
            'UTF8'
        )
    ),
    'hex'
)
"""


def _request_digest(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
    field_id: UUID,
    value: object,
    expected_sequence: int,
    reason: str,
    source_channel: str,
) -> str:
    # PostgreSQL also recomputes this exact digest from the durable revision
    # when the receipt is inserted.  Let PostgreSQL canonicalize JSONB here as
    # well, so Python and the database cannot disagree about object key order,
    # Unicode, number rendering, or insignificant JSON whitespace.
    encoded_value = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            _REQUEST_DIGEST_SQL,
            [
                actor_id,
                edition_id,
                expected_sequence,
                field_id,
                organization_id,
                reason,
                registration_id,
                source_channel,
                encoded_value,
            ],
        )
        row = cursor.fetchone()
    if row is None or not isinstance(row[0], str):
        raise ProfileExtensionValueEvidenceConflictError
    return row[0]


def _writer_authorization(
    *,
    actor: Account,
    registration: Registration,
    correlation_id: UUID,
    source_channel: str,
    operation: str,
    read: bool,
) -> tuple[str, str, frozenset[str]]:
    is_owner = actor.id == registration.account_id
    if is_owner:
        capability = VIEW_SELF_PROFILE if read else MANAGE_SELF_PROFILE
        writer_kind = ProfileExtensionValueWriterKind.OWNER
        target = resolve_owned_target(resource=registration)
    else:
        capability = VIEW_PROFILE_EXTENSIONS if read else UPDATE_PROFILE_EXTENSIONS
        writer_kind = ProfileExtensionValueWriterKind.STAFF
        target = resolve_edition_target(
            organization_id=registration.organization_id,
            edition_id=registration.edition_id,
        )
    obligations = _require_decision(
        actor=actor,
        capability_code=capability,
        target=target,
        operation=operation,
        target_type="registration.profile_extensions",
        target_id=registration.id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    return writer_kind, capability, obligations


def _fresh_actor(actor: Account) -> Account:
    current = Account.objects.filter(
        id=actor.id,
        is_active=True,
        account_kind=Account.Kind.PERSON,
    ).first()
    if current is None:
        raise ProfileExtensionValueUnavailableError
    return current


def _validate_writer_policy(
    *,
    field: RegistrationProfileExtensionField,
    writer_kind: str,
    reason: str,
) -> None:
    if writer_kind == ProfileExtensionValueWriterKind.OWNER:
        if reason:
            raise ValidationError(
                {"reason": "Attendee self-service does not accept a staff reason."},
                code="profile_extension_owner_reason_unexpected",
            )
        if field.audience_policy not in {
            ProfileExtensionAudience.SELF,
            ProfileExtensionAudience.CONFIRMED_ATTENDEES,
            ProfileExtensionAudience.PUBLIC,
        } or field.writer_policy not in {
            ProfileExtensionWriter.ATTENDEE,
            ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        }:
            raise AuthorizationDenied(
                "This profile field is unavailable.",
                reason_code="profile_extension_staff_managed",
            )
        return
    if not reason:
        raise ValidationError(
            {"reason": "Staff changes require a reason."},
            code="profile_extension_staff_reason_required",
        )
    if field.writer_policy not in {
        ProfileExtensionWriter.REGISTRATION_STAFF,
        ProfileExtensionWriter.ATTENDEE_AND_STAFF,
    }:
        raise AuthorizationDenied(
            "This profile field is unavailable.",
            reason_code="profile_extension_attendee_managed",
        )


def _staff_audience_decision(
    *,
    actor: Account,
    field: RegistrationProfileExtensionField,
) -> PolicyDecision | None:
    if field.audience_policy == ProfileExtensionAudience.REGISTRATION_STAFF:
        target = resolve_edition_target(
            organization_id=field.organization_id,
            edition_id=field.edition_id,
        )
    elif (
        field.audience_policy == ProfileExtensionAudience.DEPARTMENT
        and field.audience_department_id is not None
    ):
        target = resolve_department_target(
            organization_id=field.organization_id,
            edition_id=field.edition_id,
            department_id=field.audience_department_id,
        )
    else:
        return None
    if target is None:
        return None
    decision = decide(
        principal=actor,
        capability_code=VIEW_PROFILE_EXTENSIONS,
        resource=target,
    )
    return decision if decision.allowed else None


def _require_exact_evidence(
    receipt: RegistrationProfileExtensionValueCommandReceipt,
) -> None:
    revision = receipt.revision
    control = receipt.control
    expected_payload = {
        "field_id": str(receipt.field_id),
        "field_version": str(receipt.field.version),
        "registration_id": str(receipt.registration_id),
        "sequence": str(receipt.result_sequence),
        "writer_kind": receipt.writer_kind,
    }
    capability = (
        MANAGE_SELF_PROFILE
        if receipt.writer_kind == ProfileExtensionValueWriterKind.OWNER
        else UPDATE_PROFILE_EXTENSIONS
    )
    audit_count = AuditEvent.objects.filter(
        principal_kind="account",
        principal_id=receipt.actor_id,
        organization_id=receipt.organization_id,
        event_edition_id=receipt.edition_id,
        capability_code=capability,
        operation="registration.profile_extension.value_append",
        target_type="registration.profile_extension_value_revision",
        target_id=revision.id,
        outcome=AuditEvent.Outcome.ALLOW,
        correlation_id=receipt.correlation_id,
        changed_fields=["current_value"],
        source_channel=receipt.source_channel,
    ).count()
    events = DomainEvent.objects.filter(
        event_name="registration.profile_extension.value_appended.v1",
        schema_version=1,
        organization_id=receipt.organization_id,
        event_edition_id=receipt.edition_id,
        aggregate_type="registration.profile_extension_value",
        aggregate_id=control.id,
        aggregate_version=receipt.result_sequence,
        correlation_id=receipt.correlation_id,
        actor_kind="account",
        actor_id=receipt.actor_id,
        payload=expected_payload,
    )
    event = events.first()
    if (
        audit_count != 1
        or events.count() != 1
        or event is None
        or OutboxMessage.objects.filter(
            event=event,
            destination="internal",
        ).count()
        != 1
        or revision.registration_id != receipt.registration_id
        or revision.field_id != receipt.field_id
        or revision.actor_id != receipt.actor_id
        or revision.sequence != receipt.result_sequence
        or revision.source_channel != receipt.source_channel
        or control.registration_id != receipt.registration_id
        or control.field_key != revision.field_key
        or control.current_sequence < receipt.result_sequence
        or (
            control.current_sequence == receipt.result_sequence
            and control.latest_revision_id != revision.id
        )
    ):
        raise ProfileExtensionValueEvidenceConflictError


def _result(
    receipt: RegistrationProfileExtensionValueCommandReceipt,
    *,
    replayed: bool,
) -> ProfileExtensionValueCommandResult:
    return ProfileExtensionValueCommandResult(
        registration_id=receipt.registration_id,
        field_id=receipt.field_id,
        field_key=receipt.revision.field_key,
        field_version=receipt.field.version,
        revision_id=receipt.revision_id,
        receipt_id=receipt.id,
        result_sequence=receipt.result_sequence,
        value=receipt.revision.value,
        writer_kind=receipt.writer_kind,
        source_channel=receipt.source_channel,
        changed_at=receipt.revision.created_at,
        replayed=replayed,
    )


@transaction.atomic
def authorize_profile_extension_value_write_scope(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> UUID:
    """Authorize one exact registration before an adapter parses command input.

    This is an early non-disclosing gate only. The append command repeats the
    decision under its registration lock and once more immediately before the
    durable receipt is created.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    registration_id : UUID
        The attendee registration identifier within the edition scope.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str
        The closed channel code identifying where the request originated.

    Returns
    -------
    UUID
        The resolved UUID for authorize profile extension value write scope.

    Raises
    ------
    ProfileExtensionValueUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    """
    organization_id = _strict_uuid(organization_id, field="organization_id")
    edition_id = _strict_uuid(edition_id, field="edition_id")
    registration_id = _strict_uuid(registration_id, field="registration_id")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    source_channel = _strict_source_channel(source_channel)
    current_actor = _fresh_actor(actor)
    registration = Registration.objects.filter(
        id=registration_id,
        organization_id=organization_id,
        edition_id=edition_id,
    ).first()
    if registration is None:
        raise ProfileExtensionValueUnavailableError
    _writer_authorization(
        actor=current_actor,
        registration=registration,
        correlation_id=correlation_id,
        source_channel=source_channel,
        operation="registration.profile_extension.value_append",
        read=False,
    )
    return registration.id


@transaction.atomic
def append_profile_extension_value(  # noqa: PLR0915
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
    field_id: UUID,
    value: object,
    expected_sequence: int,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    reason: str = "",
) -> ProfileExtensionValueCommandResult:
    """Append one exact authorized value revision with durable replay evidence.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    registration_id : UUID
        The attendee registration identifier within the edition scope.
    field_id : UUID
        The field identifier within the requested scope.
    value : object
        The untrusted input to normalize, validate, or compare.
    expected_sequence : int
        The expected expected sequence used to reject stale updates.
    retry_key : UUID
        The stable key that makes an exact command retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None
        The correlation identifier attached to the incoming request.
    source_channel : str
        The closed channel code identifying where the request originated.
    reason : str, default=''
        The operator-supplied rationale recorded with the change.

    Returns
    -------
    ProfileExtensionValueCommandResult
        The updated ProfileExtensionValueCommandResult after the transition is
        committed.

    Raises
    ------
    ProfileExtensionValueRetryConflictError
        If a retry key is reused with different command intent.
    ProfileExtensionValueSequenceConflictError
        If the operation encounters a profile extension value sequence conflict
        condition.
    ProfileExtensionValueUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    organization_id = _strict_uuid(organization_id, field="organization_id")
    edition_id = _strict_uuid(edition_id, field="edition_id")
    registration_id = _strict_uuid(registration_id, field="registration_id")
    field_id = _strict_uuid(field_id, field="field_id")
    retry_key = _strict_uuid(retry_key, field="retry_key")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    request_id = (
        _strict_uuid(request_id, field="request_id") if request_id is not None else None
    )
    expected_sequence = _strict_sequence(expected_sequence)
    source_channel = _strict_source_channel(source_channel)
    value = _bounded_json(value)
    reason = _reason(reason)
    actor = _fresh_actor(actor)
    registration = (
        Registration.objects.select_for_update()
        .select_related("account")
        .filter(
            id=registration_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .first()
    )
    if registration is None:
        raise ProfileExtensionValueUnavailableError
    writer_kind, capability, obligations = _writer_authorization(
        actor=actor,
        registration=registration,
        correlation_id=correlation_id,
        source_channel=source_channel,
        operation="registration.profile_extension.value_append",
        read=False,
    )
    replay = (
        RegistrationProfileExtensionValueCommandReceipt.objects.select_for_update()
        .select_related("control", "revision", "field")
        .filter(
            actor=actor,
            registration=registration,
            retry_key=retry_key,
        )
        .first()
    )
    if replay is not None:
        normalized_value = _normalize_profile_extension_value(replay.field, value)
        if replay.field.required and normalized_value in (None, "", []):
            raise ValidationError(
                {"value": "This profile field is required."},
                code="required_profile_extension_value",
            )
        digest = _request_digest(
            actor_id=actor.id,
            organization_id=organization_id,
            edition_id=edition_id,
            registration_id=registration_id,
            field_id=field_id,
            value=normalized_value,
            expected_sequence=expected_sequence,
            reason=reason,
            source_channel=source_channel,
        )
        if replay.request_digest != digest:
            raise ProfileExtensionValueRetryConflictError
        _require_exact_evidence(replay)
        return _result(replay, replayed=True)
    field = (
        RegistrationProfileExtensionField.objects.select_for_update()
        .filter(
            id=field_id,
            organization_id=organization_id,
            edition_id=edition_id,
            status=ProfileExtensionStatus.ACTIVE,
        )
        .first()
    )
    if field is None:
        raise ProfileExtensionValueUnavailableError
    _validate_writer_policy(field=field, writer_kind=writer_kind, reason=reason)
    normalized_value = _normalize_profile_extension_value(field, value)
    if field.required and normalized_value in (None, "", []):
        raise ValidationError(
            {"value": "This profile field is required."},
            code="required_profile_extension_value",
        )
    digest = _request_digest(
        actor_id=actor.id,
        organization_id=organization_id,
        edition_id=edition_id,
        registration_id=registration_id,
        field_id=field_id,
        value=normalized_value,
        expected_sequence=expected_sequence,
        reason=reason,
        source_channel=source_channel,
    )
    control = (
        RegistrationProfileExtensionValueControl.objects.select_for_update()
        .filter(registration=registration, field_key=field.key)
        .first()
    )
    if control is None:
        control = RegistrationProfileExtensionValueControl.objects.create(
            registration=registration,
            organization_id=organization_id,
            edition_id=edition_id,
            field_key=field.key,
            current_sequence=0,
        )
    if control.current_sequence != expected_sequence:
        raise ProfileExtensionValueSequenceConflictError
    result_sequence = expected_sequence + 1
    stored_value = (
        Value(
            None,
            output_field=RegistrationProfileExtensionValueRevision._meta.get_field(  # noqa: SLF001
                "value"
            ),
        )
        if normalized_value is None
        else normalized_value
    )
    revision = RegistrationProfileExtensionValueRevision.objects.create(
        registration=registration,
        organization_id=organization_id,
        edition_id=edition_id,
        field=field,
        field_key=field.key,
        sequence=result_sequence,
        value=stored_value,
        actor=actor,
        source_channel=source_channel,
        reason=reason,
    )
    if normalized_value is None:
        revision.refresh_from_db()
    control.current_sequence = result_sequence
    control.latest_revision = revision
    control.save(update_fields=("current_sequence", "latest_revision", "updated_at"))
    append_audit(
        _audit_record(
            actor=actor,
            capability_code=capability,
            operation="registration.profile_extension.value_append",
            organization_id=organization_id,
            edition_id=edition_id,
            target_type="registration.profile_extension_value_revision",
            target_id=revision.id,
            correlation_id=correlation_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=(
                "attendee_profile_extension"
                if writer_kind == ProfileExtensionValueWriterKind.OWNER
                else "staff_profile_extension"
            ),
            obligations=obligations,
            changed_fields=("current_value",),
            source_channel=source_channel,
        )
    )
    publish_domain_event(
        DomainEventRecord(
            event_name="registration.profile_extension.value_appended.v1",
            schema_version=1,
            organization_id=organization_id,
            event_edition_id=edition_id,
            aggregate_type="registration.profile_extension_value",
            aggregate_id=control.id,
            aggregate_version=result_sequence,
            payload={
                "field_id": str(field.id),
                "field_version": str(field.version),
                "registration_id": str(registration.id),
                "sequence": str(result_sequence),
                "writer_kind": writer_kind,
            },
            correlation_id=correlation_id,
            causation_id=None,
            actor_kind="account",
            actor_id=actor.id,
            retention_class="registration-personal",
        ),
        destination="internal",
        workload_pool="core",
    )
    # A role grant or account state may change while value normalization and
    # evidence are assembled. Re-evaluate from current database state before
    # the durable receipt makes the mutation committable.
    actor = _fresh_actor(actor)
    _writer_authorization(
        actor=actor,
        registration=registration,
        correlation_id=correlation_id,
        source_channel=source_channel,
        operation="registration.profile_extension.value_append",
        read=False,
    )
    receipt = RegistrationProfileExtensionValueCommandReceipt.objects.create(
        control=control,
        registration=registration,
        organization_id=organization_id,
        edition_id=edition_id,
        field=field,
        revision=revision,
        actor=actor,
        writer_kind=writer_kind,
        retry_key=retry_key,
        request_digest=digest,
        expected_sequence=expected_sequence,
        result_sequence=result_sequence,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )
    _require_exact_evidence(receipt)
    return _result(receipt, replayed=False)


@transaction.atomic
def read_profile_extension_values(  # noqa: PLR0912, PLR0915
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> ProfileExtensionValueWorkspace:
    """Return one bounded, audited, policy-filtered current-value projection.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    registration_id : UUID
        The attendee registration identifier within the edition scope.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str
        The closed channel code identifying where the request originated.

    Returns
    -------
    ProfileExtensionValueWorkspace
        The ProfileExtensionValueWorkspace produced by read profile extension
        values.

    Raises
    ------
    ProfileExtensionValueLimitExceededError
        If the operation encounters a profile extension value limit exceeded
        condition.
    ProfileExtensionValueUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    """
    organization_id = _strict_uuid(organization_id, field="organization_id")
    edition_id = _strict_uuid(edition_id, field="edition_id")
    registration_id = _strict_uuid(registration_id, field="registration_id")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    source_channel = _strict_source_channel(source_channel)
    actor = _fresh_actor(actor)
    registration = (
        Registration.objects.select_for_update()
        .select_related("account")
        .filter(
            id=registration_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .first()
    )
    if registration is None:
        raise ProfileExtensionValueUnavailableError
    is_owner = actor.id == registration.account_id
    if is_owner:
        writer_kind, capability, obligations = _writer_authorization(
            actor=actor,
            registration=registration,
            correlation_id=correlation_id,
            source_channel=source_channel,
            operation="registration.profile_extension.values_read",
            read=True,
        )
    else:
        writer_kind = ProfileExtensionValueWriterKind.STAFF
        capability = VIEW_PROFILE_EXTENSIONS
        obligations = frozenset()
    fields_query = RegistrationProfileExtensionField.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
        status=ProfileExtensionStatus.ACTIVE,
    )
    if is_owner:
        fields_query = fields_query.filter(
            audience_policy__in=(
                ProfileExtensionAudience.SELF,
                ProfileExtensionAudience.CONFIRMED_ATTENDEES,
                ProfileExtensionAudience.PUBLIC,
            )
        )
    else:
        fields_query = fields_query.filter(
            audience_policy__in=(
                ProfileExtensionAudience.REGISTRATION_STAFF,
                ProfileExtensionAudience.DEPARTMENT,
            )
        ).select_related("audience_department")
    candidate_fields = tuple(
        fields_query.order_by("position", "key", "id")[
            : MAX_PROFILE_EXTENSION_FIELDS + 1
        ]
    )
    if len(candidate_fields) > MAX_PROFILE_EXTENSION_FIELDS:
        raise ProfileExtensionValueLimitExceededError
    staff_decisions: dict[UUID, PolicyDecision] = {}
    if is_owner:
        fields = candidate_fields
    else:
        for field in candidate_fields:
            decision = _staff_audience_decision(actor=actor, field=field)
            if decision is not None:
                staff_decisions[field.id] = decision
        fields = tuple(
            field for field in candidate_fields if field.id in staff_decisions
        )
        if not fields:
            raise ProfileExtensionValueUnavailableError
        obligations = frozenset(
            obligation
            for decision in staff_decisions.values()
            for obligation in decision.obligations
        )
    controls = {
        control.field_key: control
        for control in RegistrationProfileExtensionValueControl.objects.filter(
            registration=registration,
            organization_id=organization_id,
            edition_id=edition_id,
            field_key__in=[field.key for field in fields],
        ).select_related("latest_revision")
    }
    projections: list[ProfileExtensionValueFieldProjection] = []
    for field in fields:
        control = controls.get(field.key)
        revision = control.latest_revision if control is not None else None
        can_write = (
            field.writer_policy
            in {
                ProfileExtensionWriter.ATTENDEE,
                ProfileExtensionWriter.ATTENDEE_AND_STAFF,
            }
            if writer_kind == ProfileExtensionValueWriterKind.OWNER
            else False
        )
        if not is_owner and field.writer_policy in {
            ProfileExtensionWriter.REGISTRATION_STAFF,
            ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        }:
            update_target = resolve_edition_target(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            can_write = bool(
                update_target is not None
                and decide(
                    principal=actor,
                    capability_code=UPDATE_PROFILE_EXTENSIONS,
                    resource=update_target,
                ).allowed
            )
        projections.append(
            ProfileExtensionValueFieldProjection(
                field_id=field.id,
                field_key=field.key,
                field_version=field.version,
                label=field.label,
                help_text=field.help_text,
                field_type=field.field_type,
                options=tuple(field.options),
                purpose=field.purpose,
                classification=field.classification,
                audience_policy=field.audience_policy,
                audience_department_id=field.audience_department_id,
                required=field.required,
                writer_policy=field.writer_policy,
                can_write=can_write,
                current_value=revision.value if revision is not None else None,
                current_sequence=(control.current_sequence if control else 0),
                updated_at=revision.created_at if revision is not None else None,
            )
        )
    # Reauthorize after the complete bounded projection and before audit/release.
    current_actor = _fresh_actor(actor)
    if is_owner:
        _writer_authorization(
            actor=current_actor,
            registration=registration,
            correlation_id=correlation_id,
            source_channel=source_channel,
            operation="registration.profile_extension.values_read",
            read=True,
        )
    elif any(
        _staff_audience_decision(actor=current_actor, field=field) is None
        for field in fields
    ):
        raise ProfileExtensionValueUnavailableError
    snapshot_digest = canonical_digest(
        {
            "contract": "maru.registration-profile-extension-value-projection.v1",
            "registration_id": str(registration.id),
            "fields": [
                {
                    "field_id": str(item.field_id),
                    "field_version": item.field_version,
                    "current_sequence": item.current_sequence,
                }
                for item in projections
            ],
        }
    )
    append_audit(
        _audit_record(
            actor=current_actor,
            capability_code=capability,
            operation="registration.profile_extension.values_read",
            organization_id=organization_id,
            edition_id=edition_id,
            target_type="registration.registration",
            target_id=registration.id,
            correlation_id=correlation_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="profile_extension_projection_allowed",
            obligations=obligations,
            source_channel=source_channel,
            target_count=len(projections),
        )
    )
    return ProfileExtensionValueWorkspace(
        registration_id=registration.id,
        snapshot_digest=snapshot_digest,
        fields=tuple(projections),
    )


@transaction.atomic
def read_directory_profile_extension_values(
    *,
    actor: Account | None,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> dict[UUID, tuple[DirectoryProfileExtensionProjection, ...]]:
    """Return consent-gated minimized public/confirmed-attendee values.

    Consent, subject confirmation, and viewer confirmation are all rechecked
    immediately before release, so a withdrawal or lost confirmation cannot
    wait for a cache or publication cleanup job.

    Parameters
    ----------
    actor : Account | None
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str
        The closed channel code identifying where the request originated.

    Returns
    -------
    dict[UUID, tuple[DirectoryProfileExtensionProjection, ...]]
        The matching read directory profile extension values records in
        deterministic order.

    Raises
    ------
    ProfileExtensionValueLimitExceededError
        If the operation encounters a profile extension value limit exceeded
        condition.
    """
    organization_id = _strict_uuid(organization_id, field="organization_id")
    edition_id = _strict_uuid(edition_id, field="edition_id")
    correlation_id = _strict_uuid(correlation_id, field="correlation_id")
    source_channel = _strict_source_channel(source_channel)
    current_actor = None
    if actor is not None:
        current_actor = Account.objects.filter(
            id=actor.id,
            is_active=True,
            account_kind=Account.Kind.PERSON,
        ).first()
    viewer_confirmed = bool(
        current_actor is not None
        and Registration.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            account=current_actor,
            state__in=(Registration.State.CONFIRMED, Registration.State.CHECKED_IN),
        ).exists()
    )
    audience_policies = [ProfileExtensionAudience.PUBLIC]
    if viewer_confirmed:
        audience_policies.append(ProfileExtensionAudience.CONFIRMED_ATTENDEES)
    fields = tuple(
        RegistrationProfileExtensionField.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status=ProfileExtensionStatus.ACTIVE,
            review_status=ProfileExtensionReviewStatus.APPROVED,
            audience_policy__in=audience_policies,
        ).order_by("position", "key", "id")[: MAX_PROFILE_EXTENSION_FIELDS + 1]
    )
    if len(fields) > MAX_PROFILE_EXTENSION_FIELDS:
        raise ProfileExtensionValueLimitExceededError
    eligible_registration_ids = tuple(
        AttendeeRegistrationProfile.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            directory_visible=True,
            directory_consent_version=DIRECTORY_CONSENT_VERSION,
            registration__state__in=(
                Registration.State.CONFIRMED,
                Registration.State.CHECKED_IN,
            ),
        ).values_list("registration_id", flat=True)
    )
    controls = tuple(
        RegistrationProfileExtensionValueControl.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            registration_id__in=eligible_registration_ids,
            field_key__in=[field.key for field in fields],
        )
        .select_related("latest_revision")
        .order_by("registration_id", "field_key", "id")[
            : MAX_DIRECTORY_PROFILE_EXTENSION_VALUES + 1
        ]
    )
    if len(controls) > MAX_DIRECTORY_PROFILE_EXTENSION_VALUES:
        raise ProfileExtensionValueLimitExceededError
    field_by_key = {field.key: field for field in fields}
    field_order = {field.id: ordinal for ordinal, field in enumerate(fields)}
    projections: dict[UUID, list[DirectoryProfileExtensionProjection]] = {}
    for control in controls:
        field = field_by_key.get(control.field_key)
        revision = control.latest_revision
        if field is None or revision is None or revision.value in (None, "", []):
            continue
        projections.setdefault(control.registration_id, []).append(
            DirectoryProfileExtensionProjection(
                field_id=field.id,
                label=field.label,
                value=revision.value,
                audience_policy=field.audience_policy,
            )
        )
    # Recheck both sides of the audience relationship at the release boundary.
    valid_registration_ids = frozenset(
        AttendeeRegistrationProfile.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            directory_visible=True,
            directory_consent_version=DIRECTORY_CONSENT_VERSION,
            registration__state__in=(
                Registration.State.CONFIRMED,
                Registration.State.CHECKED_IN,
            ),
            registration_id__in=projections,
        ).values_list("registration_id", flat=True)
    )
    if viewer_confirmed:
        viewer_confirmed = bool(
            current_actor is not None
            and Registration.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                account=current_actor,
                state__in=(
                    Registration.State.CONFIRMED,
                    Registration.State.CHECKED_IN,
                ),
            ).exists()
        )
    released = {
        registration_id: tuple(
            item
            for item in sorted(
                items,
                key=lambda projection: field_order[projection.field_id],
            )
            if item.audience_policy == ProfileExtensionAudience.PUBLIC
            or viewer_confirmed
        )
        for registration_id, items in projections.items()
        if registration_id in valid_registration_ids
    }
    released = {key: value for key, value in released.items() if value}
    append_audit(
        AuditRecord(
            principal_kind="account" if current_actor is not None else "anonymous",
            principal_id=current_actor.id if current_actor is not None else None,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=VIEW_PROFILE_EXTENSIONS,
            operation="registration.profile_extension.directory_read",
            target_type="registration.profile_extension_directory",
            target_id=edition_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=(
                "confirmed_attendee_directory_consent"
                if viewer_confirmed
                else "public_directory_consent"
            ),
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("audit_sensitive_read",),
            safe_metadata={
                "contract_version": "registration-profile-directory-audience-v1",
                "target_count": sum(len(items) for items in released.values()),
            },
            retention_class="registration-personal",
        )
    )
    return released
