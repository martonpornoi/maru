"""Authorized application services for edition state transitions."""

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import date
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION, require_capability
from maru.authorization.enforcement import (
    BulkTargetDeniedError,
    BulkTargetUnavailableError,
    freeze_bulk_targets,
)
from maru.authorization.policy import ResourceScope, decide
from maru.authorization.services import AuthorizationDenied
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import (
    MAX_EDITION_SPAN_DAYS,
    EditionCreationReceipt,
    EditionLifecycleTransition,
    EventEdition,
)
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization

MAX_EDITION_NAME_LENGTH = 160
MAX_EDITION_SLUG_LENGTH = 80
MAX_EDITION_SLUG_CANDIDATES = 10_000

EDITION_CREATION_FIELDS = (
    "organization",
    "series",
    "name",
    "slug",
    "lifecycle",
    "aggregate_version",
    "time_zone",
    "language_codes",
    "currency_codes",
    "starts_on",
    "ends_on",
)

EDITION_PROFILE_FIELDS = (
    "name",
    "starts_on",
    "ends_on",
    "time_zone",
    "language_codes",
    "currency_codes",
)

EDITION_PROFILE_EDITABLE_LIFECYCLES = frozenset(
    {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
    }
)


@dataclass(frozen=True, slots=True)
class EventEditionDetails:
    name: str
    time_zone: str
    language_codes: tuple[str, ...]
    currency_codes: tuple[str, ...]
    starts_on: date
    ends_on: date


@dataclass(frozen=True, slots=True)
class EventEditionCreationResult:
    edition: EventEdition
    replayed: bool


@dataclass(frozen=True, slots=True)
class EventEditionUpdateResult:
    edition: EventEdition
    changed_fields: tuple[str, ...]


def _normalize_edition_details(details: EventEditionDetails) -> EventEditionDetails:
    name = " ".join(details.name.split())
    if not name:
        raise ValidationError(
            {"name": "Enter an edition name."},
            code="edition_name_required",
        )
    if len(name) > MAX_EDITION_NAME_LENGTH:
        raise ValidationError(
            {
                "name": (
                    "Ensure this value has at most "
                    f"{MAX_EDITION_NAME_LENGTH} characters."
                )
            },
            code="edition_name_too_long",
        )
    if details.ends_on < details.starts_on:
        raise ValidationError(
            {"ends_on": "The end date cannot be before the start date."},
            code="edition_end_before_start",
        )
    if (details.ends_on - details.starts_on).days > MAX_EDITION_SPAN_DAYS:
        raise ValidationError(
            {
                "ends_on": (
                    f"An edition date range cannot exceed {MAX_EDITION_SPAN_DAYS} days."
                )
            },
            code="edition_date_range_too_long",
        )
    return replace(
        details,
        name=name,
        time_zone=details.time_zone.strip(),
        language_codes=tuple(
            str(code).strip().lower() for code in details.language_codes
        ),
        currency_codes=tuple(
            str(code).strip().upper() for code in details.currency_codes
        ),
    )


def _edition_slug_candidate(base: str, number: int) -> str:
    suffix = "" if number == 1 else f"-{number}"
    stem = base[: MAX_EDITION_SLUG_LENGTH - len(suffix)].rstrip("-")
    return f"{stem}{suffix}"


def _create_edition_with_generated_slug(
    *,
    organization: Organization,
    series: ConventionSeries,
    details: EventEditionDetails,
) -> EventEdition:
    base = slugify(details.name)[:MAX_EDITION_SLUG_LENGTH].strip("-") or "edition"
    for number in range(1, MAX_EDITION_SLUG_CANDIDATES + 1):
        candidate = _edition_slug_candidate(base, number)
        scoped_slug = EventEdition.objects.filter(
            series=series,
            slug__iexact=candidate,
        )
        if scoped_slug.exists():
            continue
        try:
            with transaction.atomic():
                return EventEdition.objects.create(
                    organization=organization,
                    series=series,
                    slug=candidate,
                    name=details.name,
                    lifecycle=EventEdition.Lifecycle.DRAFT,
                    lifecycle_version=0,
                    aggregate_version=1,
                    time_zone=details.time_zone,
                    language_codes=list(details.language_codes),
                    currency_codes=list(details.currency_codes),
                    starts_on=details.starts_on,
                    ends_on=details.ends_on,
                )
        except (IntegrityError, ValidationError):
            if scoped_slug.exists():
                continue
            raise
    raise ValidationError(
        {"name": "Maru could not generate an available edition URL name."},
        code="edition_slug_unavailable",
    )


def _edition_creation_digest(
    *,
    organization_id: UUID,
    series_id: UUID,
    details: EventEditionDetails,
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "series_id": str(series_id),
        "name": details.name,
        "time_zone": details.time_zone,
        "language_codes": list(details.language_codes),
        "currency_codes": list(details.currency_codes),
        "starts_on": details.starts_on.isoformat(),
        "ends_on": details.ends_on.isoformat(),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _idempotency_key_hash(idempotency_key: UUID) -> str:
    return hashlib.sha256(str(idempotency_key).encode()).hexdigest()


def _require_edition_capability(
    *,
    actor: Account,
    capability_code: str,
    organization_id: UUID,
    edition_id: UUID | None = None,
) -> tuple[str, tuple[str, ...]]:
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=ResourceScope(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "The event edition operation is not permitted.",
            reason_code=decision.reason_code,
        )
    return decision.reason_code, tuple(sorted(decision.obligations))


def create_event_edition(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    details: EventEditionDetails,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> EventEditionCreationResult:
    """Create one Draft edition with idempotent audit and outbox evidence."""

    reason_code, obligations = _require_edition_capability(
        actor=actor,
        capability_code="events.create",
        organization_id=organization_id,
    )
    normalized = _normalize_edition_details(details)
    request_digest = _edition_creation_digest(
        organization_id=organization_id,
        series_id=series_id,
        details=normalized,
    )

    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(id=organization_id)
        series = ConventionSeries.objects.select_for_update().get(
            id=series_id,
            organization=organization,
        )
        existing_receipt = (
            EditionCreationReceipt.objects.select_related("edition")
            .filter(
                actor_id=actor.id,
                series_id=series.id,
                idempotency_key=idempotency_key,
            )
            .first()
        )
        if existing_receipt is not None:
            if existing_receipt.request_digest != request_digest:
                raise ValidationError(
                    {
                        "idempotency_key": ValidationError(
                            (
                                "This creation key was already used with "
                                "different edition details."
                            ),
                            code="edition_creation_idempotency_conflict",
                        )
                    }
                )
            return EventEditionCreationResult(
                edition=existing_receipt.edition,
                replayed=True,
            )

        if organization.lifecycle == Organization.Lifecycle.CLOSED:
            raise ValidationError(
                "A Closed organization cannot create an event edition.",
                code="edition_parent_closed",
            )
        if not series.is_active:
            raise ValidationError(
                "An inactive convention series cannot create an event edition.",
                code="edition_series_inactive",
            )

        edition = _create_edition_with_generated_slug(
            organization=organization,
            series=series,
            details=normalized,
        )
        EditionCreationReceipt.objects.create(
            edition=edition,
            organization_id=organization.id,
            series_id=series.id,
            actor_id=actor.id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        audit_event = append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor.id,
                principal_context_id=None,
                organization_id=organization.id,
                event_edition_id=edition.id,
                capability_code="events.create",
                operation="events.edition.create",
                target_type="events.event_edition",
                target_id=edition.id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=reason_code,
                correlation_id=correlation_id,
                request_id=request_id,
                idempotency_key_hash=_idempotency_key_hash(idempotency_key),
                source_channel=source_channel,
                obligations=obligations,
                changed_fields=EDITION_CREATION_FIELDS,
                safe_metadata={"policy_version": POLICY_VERSION},
            )
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="events.edition.created.v1",
                schema_version=1,
                organization_id=organization.id,
                event_edition_id=edition.id,
                aggregate_type="events.event_edition",
                aggregate_id=edition.id,
                aggregate_version=edition.aggregate_version,
                payload={
                    "aggregate_version": str(edition.aggregate_version),
                    "lifecycle": edition.lifecycle,
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=actor.id,
            ),
            workload_pool="core",
        )
        return EventEditionCreationResult(edition=edition, replayed=False)


def update_event_edition(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    expected_aggregate_version: int,
    details: EventEditionDetails,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> EventEditionUpdateResult:
    """Update editable edition profile fields with optimistic concurrency."""

    reason_code, obligations = _require_edition_capability(
        actor=actor,
        capability_code="events.change_profile",
        organization_id=organization_id,
        edition_id=edition_id,
    )
    normalized = _normalize_edition_details(details)

    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(id=organization_id)
        series = ConventionSeries.objects.select_for_update().get(
            id=series_id,
            organization=organization,
        )
        edition = EventEdition.objects.select_for_update().get(
            id=edition_id,
            organization=organization,
            series=series,
        )
        if organization.lifecycle == Organization.Lifecycle.CLOSED:
            raise ValidationError(
                {
                    "lifecycle": ValidationError(
                        "A Closed organization's editions are read-only.",
                        code="edition_parent_closed",
                    )
                }
            )
        if edition.lifecycle not in EDITION_PROFILE_EDITABLE_LIFECYCLES:
            raise ValidationError(
                {
                    "lifecycle": ValidationError(
                        "Only Draft or Preparing edition details can be changed.",
                        code="edition_profile_read_only",
                    )
                }
            )
        if edition.aggregate_version != expected_aggregate_version:
            raise ValidationError(
                {
                    "expected_aggregate_version": ValidationError(
                        (
                            "This edition changed after the page was loaded. "
                            "Reload it before saving your changes."
                        ),
                        code="stale_edition_version",
                    )
                }
            )
        values: dict[str, object] = {
            "name": normalized.name,
            "time_zone": normalized.time_zone,
            "language_codes": list(normalized.language_codes),
            "currency_codes": list(normalized.currency_codes),
            "starts_on": normalized.starts_on,
            "ends_on": normalized.ends_on,
        }
        changed_fields = tuple(
            field_name
            for field_name in EDITION_PROFILE_FIELDS
            if getattr(edition, field_name) != values[field_name]
        )
        if not changed_fields:
            return EventEditionUpdateResult(edition=edition, changed_fields=())

        for field_name in changed_fields:
            setattr(edition, field_name, values[field_name])
        edition.aggregate_version += 1
        edition.save(
            update_fields=(*changed_fields, "aggregate_version", "updated_at"),
        )
        audited_fields = (*changed_fields, "aggregate_version")
        audit_event = append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor.id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition.id,
                capability_code="events.change_profile",
                operation="events.edition.update",
                target_type="events.event_edition",
                target_id=edition.id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=reason_code,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                obligations=obligations,
                changed_fields=audited_fields,
                safe_metadata={"policy_version": POLICY_VERSION},
            )
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="events.edition.details_updated.v1",
                schema_version=1,
                organization_id=organization_id,
                event_edition_id=edition.id,
                aggregate_type="events.event_edition",
                aggregate_id=edition.id,
                aggregate_version=edition.aggregate_version,
                payload={
                    "aggregate_version": str(edition.aggregate_version),
                    "changed_fields": ",".join(changed_fields),
                },
                correlation_id=correlation_id,
                causation_id=audit_event.id,
                actor_kind="account",
                actor_id=actor.id,
            ),
            workload_pool="core",
        )
        return EventEditionUpdateResult(
            edition=edition,
            changed_fields=changed_fields,
        )


ALLOWED_TRANSITIONS: dict[str, Collection[str]] = {
    EventEdition.Lifecycle.DRAFT: {
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.CANCELLED,
    },
    EventEdition.Lifecycle.PREPARING: {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.CANCELLED,
    },
    EventEdition.Lifecycle.READY: {
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.LIVE,
        EventEdition.Lifecycle.CANCELLED,
    },
    EventEdition.Lifecycle.LIVE: {EventEdition.Lifecycle.CLOSING},
    EventEdition.Lifecycle.CLOSING: {EventEdition.Lifecycle.ARCHIVED},
    EventEdition.Lifecycle.ARCHIVED: set(),
    EventEdition.Lifecycle.CANCELLED: set(),
}


def _transition_audit_record(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    outcome: str,
    reason_code: str,
    obligations: tuple[str, ...] = (),
    changed_fields: tuple[str, ...] = (),
) -> AuditRecord:
    return AuditRecord(
        principal_kind="account",
        principal_id=actor.id,
        principal_context_id=None,
        organization_id=organization_id,
        event_edition_id=edition_id,
        capability_code="events.transition",
        operation="events.edition.transition",
        target_type="events.event_edition",
        target_id=edition_id,
        outcome=outcome,
        reason_code=reason_code,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=changed_fields,
        safe_metadata={"policy_version": POLICY_VERSION},
    )


def _bulk_transition_audit_record(
    *,
    actor: Account,
    organization_id: UUID,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    target_count: int,
    outcome: str,
    reason_code: str,
) -> AuditRecord:
    obligations = tuple(sorted(require_capability("events.transition").obligations))
    return AuditRecord(
        principal_kind="account",
        principal_id=actor.id,
        principal_context_id=None,
        organization_id=organization_id,
        event_edition_id=None,
        capability_code="events.transition",
        operation="events.edition.bulk_transition",
        target_type="events.event_edition_set",
        target_id=None,
        outcome=outcome,
        reason_code=reason_code,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=(
            ("lifecycle", "lifecycle_version", "aggregate_version")
            if outcome == AuditEvent.Outcome.ALLOW
            else ()
        ),
        safe_metadata={
            "policy_version": POLICY_VERSION,
            "target_count": target_count,
        },
    )


def _require_valid_transition(edition: EventEdition, *, to_state: str) -> None:
    allowed = ALLOWED_TRANSITIONS[edition.lifecycle]
    if to_state not in allowed:
        raise ValidationError(
            {
                "lifecycle": (
                    f"Cannot transition an edition from {edition.lifecycle} "
                    f"to {to_state}."
                )
            },
            code="invalid_transition",
        )


def transition_edition(
    *,
    organization_id: UUID,
    edition_id: UUID,
    to_state: str,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> EventEdition:
    decision = decide(
        principal=actor,
        capability_code="events.transition",
        resource=ResourceScope(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        append_audit(
            _transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=decision.reason_code,
            )
        )
        raise AuthorizationDenied(
            "The edition lifecycle transition is not permitted.",
            reason_code=decision.reason_code,
        )

    normalized_reason = reason.strip()
    if not normalized_reason:
        append_audit(
            _transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="reason_required",
                obligations=tuple(sorted(decision.obligations)),
            )
        )
        raise ValidationError(
            {"reason": "A transition reason is required."},
            code="reason_required",
        )

    try:
        with transaction.atomic():
            edition = EventEdition.objects.select_for_update().get(
                pk=edition_id,
                organization_id=organization_id,
            )
            _require_valid_transition(edition, to_state=to_state)

            previous_state = edition.lifecycle
            if to_state == EventEdition.Lifecycle.ARCHIVED:
                from maru.events.closure import assert_archive_ready  # noqa: PLC0415
                from maru.participation.services import (  # noqa: PLC0415
                    snapshot_participations_for_archive,
                )

                assert_archive_ready(edition)
                snapshot_participations_for_archive(edition_id=edition.id)

            edition.lifecycle = to_state
            edition.lifecycle_version += 1
            edition.aggregate_version += 1
            edition.save(
                update_fields=(
                    "lifecycle",
                    "lifecycle_version",
                    "aggregate_version",
                    "updated_at",
                )
            )
            EditionLifecycleTransition.objects.create(
                edition=edition,
                from_state=previous_state,
                to_state=to_state,
                actor_id=actor.id,
                reason=normalized_reason,
            )
            audit_event = append_audit(
                _transition_audit_record(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    source_channel=source_channel,
                    outcome=AuditEvent.Outcome.ALLOW,
                    reason_code=decision.reason_code,
                    obligations=tuple(sorted(decision.obligations)),
                    changed_fields=(
                        "lifecycle",
                        "lifecycle_version",
                        "aggregate_version",
                    ),
                )
            )
            publish_domain_event(
                DomainEventRecord(
                    event_name="events.edition.lifecycle_transitioned.v1",
                    schema_version=1,
                    organization_id=edition.organization_id,
                    event_edition_id=edition.id,
                    aggregate_type="events.event_edition",
                    aggregate_id=edition.id,
                    aggregate_version=edition.aggregate_version,
                    payload={
                        "from_state": previous_state,
                        "to_state": to_state,
                    },
                    correlation_id=correlation_id,
                    causation_id=audit_event.id,
                    actor_kind="account",
                    actor_id=actor.id,
                ),
                workload_pool="core",
            )
            return edition
    except EventEdition.DoesNotExist:
        append_audit(
            _transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="edition_not_found",
                obligations=tuple(sorted(decision.obligations)),
            )
        )
        raise
    except ValidationError:
        append_audit(
            _transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="invalid_transition",
                obligations=tuple(sorted(decision.obligations)),
            )
        )
        raise
    except Exception:
        append_audit(
            _transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="transition_failed",
                obligations=tuple(sorted(decision.obligations)),
            )
        )
        raise


def bulk_transition_editions(
    *,
    organization_id: UUID,
    edition_ids: tuple[UUID, ...],
    to_state: str,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> tuple[EventEdition, ...]:
    """Atomically transition an exact, locked, independently authorized set."""

    target_count = len(edition_ids)
    try:
        with transaction.atomic():
            targets = freeze_bulk_targets(
                trusted_queryset=EventEdition.objects.filter(
                    organization_id=organization_id
                ),
                target_ids=edition_ids,
                authorize=lambda edition: decide(
                    principal=actor,
                    capability_code="events.transition",
                    resource=ResourceScope(
                        organization_id=organization_id,
                        edition_id=edition.id,
                        state=edition.lifecycle,
                    ),
                ),
            )
            transitioned = tuple(
                transition_edition(
                    organization_id=organization_id,
                    edition_id=edition.id,
                    to_state=to_state,
                    actor=actor,
                    reason=reason,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    source_channel=source_channel,
                )
                for edition in targets
            )
            append_audit(
                _bulk_transition_audit_record(
                    actor=actor,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    source_channel=source_channel,
                    target_count=target_count,
                    outcome=AuditEvent.Outcome.ALLOW,
                    reason_code="bulk_targets_authorized",
                )
            )
            return transitioned
    except BulkTargetDeniedError as error:
        append_audit(
            _bulk_transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                target_count=target_count,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=error.reason_code,
            )
        )
        raise
    except AuthorizationDenied as error:
        append_audit(
            _bulk_transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                target_count=target_count,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=error.reason_code,
            )
        )
        raise
    except BulkTargetUnavailableError:
        append_audit(
            _bulk_transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                target_count=target_count,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="bulk_target_unavailable",
            )
        )
        raise
    except ValidationError:
        append_audit(
            _bulk_transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                target_count=target_count,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="invalid_transition",
            )
        )
        raise
    except Exception:
        append_audit(
            _bulk_transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                target_count=target_count,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="bulk_transition_failed",
            )
        )
        raise
