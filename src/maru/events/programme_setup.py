"""Atomic dormant Programme foundation setup, not operational authorization."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.events.adoption import adoption_profile, selectable_adoption_profile
from maru.events.models import EditionCreationReceipt, ProgrammeAdoptionSetupReceipt
from maru.events.programme_setup_inputs import (
    ProgrammeSetupInput,
    ProgrammeSetupMode,
    normalize_programme_setup_input,
    programme_setup_request_digest,
)
from maru.events.programme_setup_readiness import (
    programme_setup_database_integrity_is_ready,
)
from maru.events.programme_setup_writer import _programme_setup_writer
from maru.events.services import EventEditionDetails, create_event_edition
from maru.identity.queries import current_platform_administrator_is_available
from maru.organizations.programme_setup_references import (
    lock_programme_setup_foundation,
)
from maru.organizations.representation import provision_maru_operators
from maru.organizations.services import (
    ConventionSeriesCreationDetails,
    OrganizationCreationDetails,
    create_convention_series,
    create_draft_organization,
)
from maru.workforce.structure_commands import create_department

if TYPE_CHECKING:
    from maru.identity.models import Account

_PROFILE_KEY = ("programme_operations", 1)
_MAX_SOURCE_CHANNEL_LENGTH = 32


@dataclass(frozen=True, slots=True)
class ProgrammeSetupResult:
    """Return only retained setup identities, never people or current authority.

    Attributes
    ----------
    receipt_id, organization_id, series_id, edition_id, department_id, representation_id
        Opaque original result identities, including a still-unactivated root.
    replayed
        Whether the complete retained result satisfied an exact retry.
    created_organization, created_series
        Which foundation levels the original setup created rather than reused.
        Every successful setup created its edition and first Department.
    """

    receipt_id: UUID
    organization_id: UUID
    series_id: UUID
    edition_id: UUID
    department_id: UUID
    representation_id: UUID
    replayed: bool
    created_organization: bool
    created_series: bool


@dataclass(frozen=True, slots=True)
class _Foundation:
    organization_id: UUID
    series_id: UUID
    language_codes: tuple[str, ...]
    representation_id: UUID
    representation_version: int


def _conflict(message: str, code: str) -> ValidationError:
    return ValidationError(message, code=f"programme_setup_{code}")


def _require_actor(actor: Account, *, lock: bool = False) -> None:
    if (
        not actor.is_active
        or not actor.is_platform_administrator
        or not current_platform_administrator_is_available(
            account_id=actor.id, lock=lock
        )
    ):
        raise PermissionDenied("Platform administration is required.")


def _lock_key(actor_id: UUID, key: UUID) -> None:
    digest = hashlib.sha256(b"events.programme-setup@1:" + actor_id.bytes + key.bytes)
    lock_key = int.from_bytes(digest.digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])


def _result(
    receipt: ProgrammeAdoptionSetupReceipt, *, replayed: bool
) -> ProgrammeSetupResult:
    return ProgrammeSetupResult(
        receipt_id=receipt.id,
        organization_id=receipt.organization_id,
        series_id=receipt.series_id,
        edition_id=receipt.edition_id,
        department_id=receipt.department_id,
        representation_id=receipt.representation_id,
        replayed=replayed,
        created_organization=receipt.mode == ProgrammeSetupMode.NEW_FOUNDATION,
        created_series=receipt.mode != ProgrammeSetupMode.EXISTING_SERIES,
    )


def _foundation(
    *,
    actor: Account,
    details: ProgrammeSetupInput,
    correlation_id: UUID,
    source_channel: str,
) -> _Foundation:
    representation_id = None
    representation_version = None
    series_id = details.series_id
    if details.mode == ProgrammeSetupMode.NEW_FOUNDATION:
        organization = create_draft_organization(
            actor=actor,
            details=OrganizationCreationDetails(
                name=details.organization_name,
                default_language_codes=("en",),
                default_time_zone=details.time_zone,
            ),
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        organization_id = organization.id
        languages = tuple(organization.default_language_codes)
    else:
        if details.organization_id is None:
            raise _conflict(
                "Choose the original foundation again.", "foundation_unavailable"
            )
        reference = lock_programme_setup_foundation(
            organization_id=details.organization_id,
            series_id=details.series_id,
            expected_fingerprint=details.foundation_fingerprint,
        )
        if reference is None:
            raise _conflict(
                "Choose the original foundation again.", "foundation_unavailable"
            )
        organization_id = reference.organization_id
        languages = reference.default_language_codes
        representation_id = reference.representation_id
        representation_version = reference.representation_version
    if representation_id is None:
        representation = provision_maru_operators(
            actor=actor,
            organization_id=organization_id,
            reason=details.reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        representation_id = representation.id
        representation_version = representation.aggregate_version
    if series_id is None:
        series_id = create_convention_series(
            actor=actor,
            organization_id=organization_id,
            details=ConventionSeriesCreationDetails(name=details.series_name),
            correlation_id=correlation_id,
            source_channel=source_channel,
        ).id
    if representation_version is None or representation_version < 1:
        raise _conflict("The foundation is unavailable.", "foundation_unavailable")
    return _Foundation(
        organization_id,
        series_id,
        languages or ("en",),
        representation_id,
        representation_version,
    )


def _create_setup(
    *,
    actor: Account,
    details: ProgrammeSetupInput,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    digest: str,
) -> ProgrammeSetupResult:
    profile = selectable_adoption_profile(_PROFILE_KEY[0])
    if profile is None or profile.key != _PROFILE_KEY:
        raise _conflict("Programme setup is not available.", "profile_unavailable")
    if not programme_setup_database_integrity_is_ready():
        raise _conflict(
            "Programme setup integrity is unavailable.", "integrity_unavailable"
        )
    lock_retired_department_authority_boundaries()
    foundation = _foundation(
        actor=actor,
        details=details,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    edition_result = create_event_edition(
        actor=actor,
        organization_id=foundation.organization_id,
        series_id=foundation.series_id,
        details=EventEditionDetails(
            name=details.edition_name,
            time_zone=details.time_zone,
            language_codes=foundation.language_codes,
            currency_codes=("XXX",),
            starts_on=details.starts_on,
            ends_on=details.ends_on,
        ),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        request_id=correlation_id,
        source_channel=source_channel,
        adoption_profile_code=_PROFILE_KEY[0],
    )
    edition = edition_result.edition
    if (
        edition_result.replayed
        or (edition.adoption_profile_code, edition.adoption_profile_version)
        != _PROFILE_KEY
    ):
        raise _conflict(
            "This key does not identify a new complete setup.", "child_conflict"
        )
    department = create_department(
        actor=actor,
        organization_id=foundation.organization_id,
        series_id=foundation.series_id,
        edition_id=edition.id,
        name=details.department_name,
        description="",
        parent_department_id=None,
        display_order=None,
        expected_version=0,
        reason=details.reason,
        retry_key=idempotency_key,
        correlation_id=correlation_id,
        request_id=correlation_id,
        source_channel=source_channel,
    )
    if (
        department.replayed
        or department.resulting_version != 1
        or department.receipt_id is None
    ):
        raise _conflict(
            "This key does not identify a new complete setup.", "child_conflict"
        )
    _require_actor(actor, lock=True)
    receipt_id = uuid4()
    audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=foundation.organization_id,
            event_edition_id=edition.id,
            capability_code="events.create",
            operation="events.programme_adoption.setup",
            target_type="events.programme_setup_receipt",
            target_id=receipt_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="platform_administration",
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("audit",),
            changed_fields=("foundation", "edition", "department", "representation"),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="security-standard",
        )
    )
    edition_creation = EditionCreationReceipt.objects.get(
        edition_id=edition.id,
        organization_id=foundation.organization_id,
        series_id=foundation.series_id,
        actor_id=actor.id,
        idempotency_key=idempotency_key,
    )
    with _programme_setup_writer():
        receipt = ProgrammeAdoptionSetupReceipt.objects.create(
            id=receipt_id,
            organization_id=foundation.organization_id,
            series_id=foundation.series_id,
            edition_id=edition.id,
            department_id=department.department_id,
            representation_id=foundation.representation_id,
            representation_version=foundation.representation_version,
            actor_id=actor.id,
            source_audit_id=audit.id,
            edition_creation_id=edition_creation.id,
            department_creation_id=department.receipt_id,
            idempotency_key=idempotency_key,
            request_digest=digest,
            mode=details.mode,
            foundation_fingerprint=details.foundation_fingerprint,
            reason=details.reason,
        )
    return _result(receipt, replayed=False)


def setup_programme_foundation(
    *,
    actor: Account,
    details: ProgrammeSetupInput,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "service",
) -> ProgrammeSetupResult:
    """Create one accountable foundation atomically, or recover its exact result.

    Parameters
    ----------
    actor : Account
        Authenticated active platform principal, rechecked against current Identity.
    details : ProgrammeSetupInput
        Closed explicit create/reuse intent and original source fingerprint.
    idempotency_key : UUID
        Non-nil original request key, serialized together with this actor.
    correlation_id : UUID
        Non-nil audit correlation for this attempt, not part of the original intent.
    source_channel : str, default='service'
        Bounded lowercase service-channel code, not user-provided private content.

    Returns
    -------
    ProgrammeSetupResult
        Immutable original IDs without invitation, activation or operational grants.

    Raises
    ------
    PermissionDenied
        Unless the principal remains a current active platform administrator.
    ValidationError
        For malformed input, unsupported exact profile, stale foundation, conflicting
        retry or unavailable integrity. Current deployment profiles deny setup before
        opening a transaction; the dormant command is not a mounted entry point.

    Notes
    -----
    All public owner writes, their effects, setup audit and receipt share the same
    transaction. A retained complete receipt, never a child-command replay, is the
    retry authority. Errors propagate after rollback; an adapter must not disclose
    raw database failures. No failed setup is represented as successful audit evidence.
    """
    if not actor.is_active or not actor.is_platform_administrator:
        raise PermissionDenied("Platform administration is required.")
    normalized = normalize_programme_setup_input(details)
    if any(
        not isinstance(value, UUID) or value.int == 0
        for value in (actor.id, idempotency_key, correlation_id)
    ):
        raise ValidationError(
            "Use non-empty request identifiers.", code="programme_setup_request_invalid"
        )
    if (
        not isinstance(source_channel, str)
        or len(source_channel) > _MAX_SOURCE_CHANNEL_LENGTH
        or re.fullmatch(r"[a-z][a-z0-9_-]*", source_channel) is None
    ):
        raise ValidationError(
            "Use a supported request channel.", code="programme_setup_channel_invalid"
        )
    profile = adoption_profile(*_PROFILE_KEY)
    if profile is None or profile.key != _PROFILE_KEY:
        raise ValidationError(
            "Programme setup is not available.",
            code="programme_setup_profile_unavailable",
        )
    _require_actor(actor)
    digest = programme_setup_request_digest(normalized)
    with transaction.atomic():
        _lock_key(actor.id, idempotency_key)
        existing = ProgrammeAdoptionSetupReceipt.objects.filter(
            actor_id=actor.id,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            _require_actor(actor, lock=True)
            if existing.request_digest != digest:
                raise ValidationError(
                    "This setup key was used with different details.",
                    code="programme_setup_idempotency_conflict",
                )
            return _result(existing, replayed=True)
        return _create_setup(
            actor=actor,
            details=normalized,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            digest=digest,
        )
