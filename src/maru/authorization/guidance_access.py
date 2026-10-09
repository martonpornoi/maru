"""Manage exact Guidance role requests and revocation.

Closed Guidance content-role requests, actual approvals and source-backed
revocation.
"""

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from maru.audit.mutation_evidence import audited_mutation
from maru.authorization.guidance_audit import (
    guidance_authority_audit,
    publish_guidance_authority_event,
)
from maru.authorization.guidance_catalog import (
    GUIDANCE_CONTROL_CAPABILITY,
    GUIDANCE_CONTROLLER_ROLE_CODE,
    GUIDANCE_ROLE_RECIPES,
)
from maru.authorization.guidance_writer import _guidance_authority_writer
from maru.authorization.issuance import create_persistent_dual_control_issuance
from maru.authorization.models import (
    AuthorityIssuance,
    GuidanceAccessDecision,
    GuidanceAccessRequest,
    GuidanceRevocationReceipt,
    GuidanceTeam,
    RoleAssignment,
    RoleBundle,
)
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_edition_target,
)
from maru.authorization.provenance import (
    ControlHorizonMode,
    authority_issuance_is_current,
    select_authorized_control_source,
)
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.events.knowledge_scope import resolve_knowledge_edition_scope
from maru.identity.models import Account
from maru.identity.queries import (
    resolve_active_verified_person_reference,
    resolve_active_verified_person_reference_by_email,
)

_MAX_RAW_REASON_LENGTH = 4096
_MAX_REASON_LENGTH = 240
_MAX_EMAIL_LENGTH = 254


@dataclass(frozen=True, slots=True)
class GuidanceAccessResult:
    """Resolve purpose-qualified Guidance access.

    Original task and optional assignment identity; no directory or authority
    token.

    Attributes
    ----------
    request_id : UUID
        Opaque identity of the retained immutable request.
    assignment_id : UUID | None
        Resulting role assignment, or None before approval or after refusal.
    replayed : bool
        Whether this result reuses the original completed command outcome.
    """

    request_id: UUID
    assignment_id: UUID | None = None
    replayed: bool = False


def _trace(*values: UUID) -> None:
    if any(not isinstance(value, UUID) or value.int == 0 for value in values):
        raise ValidationError("Use non-empty request identities.")


def _reason(reason: str) -> str:
    if (
        not isinstance(reason, str)
        or len(reason) > _MAX_RAW_REASON_LENGTH
        or any(unicodedata.category(character).startswith("C") for character in reason)
    ):
        raise ValidationError("Enter a short access reason.")
    normalized = " ".join(unicodedata.normalize("NFC", reason).split())
    if not normalized or len(normalized) > _MAX_REASON_LENGTH:
        raise ValidationError("Enter an access reason of at most 240 characters.")
    return normalized


def _scope(
    organization_id: UUID, edition_id: UUID, *, allow_read_only: bool = False
) -> ResolvedAuthorizationTarget:
    from maru.authorization.guidance_readiness import (  # noqa: PLC0415
        require_guidance_authority_integrity,
    )

    require_guidance_authority_integrity()
    scope = resolve_knowledge_edition_scope(
        organization_id=organization_id, edition_id=edition_id, for_update=True
    )
    target = resolve_edition_target(
        organization_id=organization_id, edition_id=edition_id
    )
    if (
        scope is None
        or not scope.parents_active
        or (not allow_read_only and not scope.accepts_writes)
        or target is None
    ):
        raise PermissionDenied("Guidance access is unavailable for this event.")
    return target


def _control(
    actor: Account,
    target: ResolvedAuthorizationTarget,
    *,
    role: str,
    effective_from: datetime,
    expires_at: datetime | None,
) -> AuthorityIssuance:
    if resolve_active_verified_person_reference(account_id=actor.id, lock=True) is None:
        raise PermissionDenied("Current Guidance access responsibility is required.")
    source = select_authorized_control_source(
        principal=actor,
        role=role,
        capability_code=GUIDANCE_CONTROL_CAPABILITY,
        target=target,
        requested_effective_from=effective_from,
        requested_expires_at=expires_at,
    )
    if source is None:
        raise PermissionDenied("Current Guidance access responsibility is required.")
    return AuthorityIssuance.objects.get(ordinal=source.source_issuance_ordinal)


def _request_sources(
    request: GuidanceAccessRequest, target: ResolvedAuthorizationTarget
) -> tuple[AuthorityIssuance, AuthorityIssuance]:
    for principal, source in (
        (request.requested_by_id, request.actor_source_id),
        (request.approver_id, request.approver_source_id),
    ):
        if resolve_active_verified_person_reference(
            account_id=principal, lock=True
        ) is None or not authority_issuance_is_current(
            issuance_ordinal=source,
            principal_id=principal,
            capability_code=GUIDANCE_CONTROL_CAPABILITY,
            target=target,
            requested_effective_from=request.effective_from,
            requested_expires_at=request.expires_at,
            lock=True,
        ):
            raise PermissionDenied(
                "The original Guidance responsibility is no longer "
                "current. Request access again."
            )
    return AuthorityIssuance.objects.get(
        ordinal=request.actor_source_id
    ), AuthorityIssuance.objects.get(ordinal=request.approver_source_id)


def _event(
    actor: Account,
    request: GuidanceAccessRequest,
    operation: str,
    audit_id: UUID,
    correlation_id: UUID,
) -> None:
    publish_guidance_authority_event(
        actor=actor,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        event_name="authorization.guidance_access.changed.v1",
        operation=operation,
        aggregate_type="authorization.guidance_access_request",
        aggregate_id=request.id,
        correlation_id=correlation_id,
        audit_id=audit_id,
    )


def request_guidance_access(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    recipient_email: str,
    approver_id: UUID,
    recipe_code: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    expires_at: datetime | None = None,
) -> GuidanceAccessResult:
    """Resolve purpose-qualified Guidance access.

    Request one visible fixed content role; the named approver must answer
    personally.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    organization_id : UUID
        Exact organization owning the requested scope.
    edition_id : UUID
        Exact event edition within the organization.
    recipient_email : str
        Exact verified account email, resolved only after purpose admission.
    approver_id : UUID
        Different current Guidance controller who will answer personally.
    recipe_code : str
        One code from the closed Guidance content-role recipe catalog.
    reason : str
        Bounded accountable explanation, retained in private evidence.
    idempotency_key : UUID
        Stable key for the original intent; changed details are rejected.
    correlation_id : UUID
        Non-empty audit trace for this attempt.
    expires_at : datetime | None, default=None
        Optional aware end of the requested access term.

    Returns
    -------
    GuidanceAccessResult
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    ValidationError
        If the immutable intent, version, acceptance or retained evidence conflicts.
    """
    _trace(organization_id, edition_id, approver_id, idempotency_key, correlation_id)
    reason = _reason(reason)
    recipe = GUIDANCE_ROLE_RECIPES.get(recipe_code)
    if recipe is None or recipe_code == GUIDANCE_CONTROLLER_ROLE_CODE:
        raise ValidationError("Choose a supported Guidance content role.")
    if not isinstance(recipient_email, str) or len(recipient_email) > _MAX_EMAIL_LENGTH:
        raise ValidationError("Enter the person's account email address.")
    email = recipient_email.strip().casefold()
    if expires_at is not None and (
        not isinstance(expires_at, datetime) or not timezone.is_aware(expires_at)
    ):
        raise ValidationError("Use a timezone-aware access end time.")
    digest = hashlib.sha256(
        json.dumps(
            [
                str(organization_id),
                str(edition_id),
                email,
                str(approver_id),
                recipe_code,
                reason,
                expires_at.isoformat() if expires_at else None,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        target = _scope(organization_id, edition_id)
        now = timezone.now()
        if (
            resolve_active_verified_person_reference(account_id=actor.id, lock=True)
            is None
            or select_authorized_control_source(
                principal=actor,
                role="actor",
                capability_code=GUIDANCE_CONTROL_CAPABILITY,
                target=target,
                requested_effective_from=now,
                requested_expires_at=None,
                horizon_mode=ControlHorizonMode.POINT_IN_TIME,
            )
            is None
        ):
            raise PermissionDenied(
                "Current Guidance access responsibility is required."
            )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                [
                    int.from_bytes(
                        hashlib.sha256(
                            actor.id.bytes + idempotency_key.bytes + b"guidance-access"
                        ).digest()[:8],
                        "big",
                        signed=True,
                    )
                ],
            )
        existing = GuidanceAccessRequest.objects.filter(
            requested_by_id=actor.id, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            if existing.request_digest != digest:
                raise ValidationError(
                    "This request key was already used with different access details."
                )
            return GuidanceAccessResult(existing.id, replayed=True)
        if expires_at is not None and expires_at <= now:
            raise ValidationError("Access must end after it starts.")
        own_source = _control(
            actor, target, role="actor", effective_from=now, expires_at=expires_at
        )
        recipient = resolve_active_verified_person_reference_by_email(
            email=email, lock=True
        )
        approver = Account.objects.filter(id=approver_id).first()
        if (
            recipient is None
            or approver is None
            or approver_id in {actor.id, recipient.account_id}
        ):
            raise ValidationError(
                "Choose another current Guidance controller who is not "
                "the access recipient."
            )
        other_source = _control(
            approver, target, role="approver", effective_from=now, expires_at=expires_at
        )
        team = GuidanceTeam.objects.filter(
            organization_id=organization_id, edition_id=edition_id
        ).first()
        role = RoleBundle.objects.filter(
            organization_id=organization_id, code=recipe.code, version=recipe.version
        ).first()
        if team is None or role is None:
            raise PermissionDenied(
                "The accepted Guidance team and recipe are unavailable."
            )
        request_id = uuid4()
        with (
            audited_mutation(
                guidance_authority_audit(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    operation="authorization.guidance.access.request",
                    target_type="authorization.guidance_access_request",
                    target_id=request_id,
                    correlation_id=correlation_id,
                )
            ) as audit,
            _guidance_authority_writer(),
        ):
            request = GuidanceAccessRequest.objects.create(
                id=request_id,
                organization_id=organization_id,
                edition_id=edition_id,
                team=team,
                requested_by=actor,
                approver=approver,
                recipient_id=recipient.account_id,
                role_bundle=role,
                actor_source=own_source,
                approver_source=other_source,
                effective_from=now,
                expires_at=expires_at,
                decision_deadline=min(now + timedelta(days=7), expires_at)
                if expires_at
                else now + timedelta(days=7),
                idempotency_key=idempotency_key,
                request_digest=digest,
                reason=reason,
                source_audit_id=audit.audit_id,
                correlation_id=correlation_id,
            )
            _event(actor, request, "requested", audit.audit_id, correlation_id)
        return GuidanceAccessResult(request.id)


def respond_to_guidance_access(
    *,
    actor: Account,
    request_id: UUID,
    expected_digest: str,
    accept: bool,
    correlation_id: UUID,
) -> GuidanceAccessResult:
    """Apply only the actual named approver's unchanged authenticated decision.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    request_id : UUID
        Opaque identifier of the original immutable request.
    expected_digest : str
        Digest of the exact recipient, recipe and approval terms.
    accept : bool
        The actual named person's authenticated acceptance or refusal.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    GuidanceAccessResult
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    ValidationError
        If the immutable intent, version, acceptance or retained evidence conflicts.
    """
    _trace(request_id, correlation_id)
    if not isinstance(accept, bool) or not isinstance(expected_digest, str):
        raise ValidationError("Answer the original access request.")
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        locator = (
            GuidanceAccessRequest.objects.filter(id=request_id, approver_id=actor.id)
            .values("organization_id", "edition_id")
            .first()
        )
        if locator is None:
            raise PermissionDenied("This approval task is unavailable.")
        target = _scope(locator["organization_id"], locator["edition_id"])
        if (
            resolve_active_verified_person_reference(account_id=actor.id, lock=True)
            is None
            or select_authorized_control_source(
                principal=actor,
                role="approver",
                capability_code=GUIDANCE_CONTROL_CAPABILITY,
                target=target,
                requested_effective_from=timezone.now(),
                requested_expires_at=None,
                horizon_mode=ControlHorizonMode.POINT_IN_TIME,
            )
            is None
        ):
            raise PermissionDenied(
                "Current Guidance access responsibility is required."
            )
        request = GuidanceAccessRequest.objects.get(id=request_id)
        own_source, other_source = _request_sources(request, target)
        if expected_digest != request.request_digest:
            raise ValidationError("The approval does not match this access request.")
        existing = GuidanceAccessDecision.objects.filter(request=request).first()
        if existing is not None:
            if existing.actor_id != actor.id or existing.accepted != accept:
                raise ValidationError("The original answer is already retained.")
            return GuidanceAccessResult(
                request.id, existing.assignment_id, replayed=True
            )
        if (
            request.decision_deadline <= timezone.now()
            or resolve_active_verified_person_reference(
                account_id=request.recipient_id, lock=True
            )
            is None
        ):
            raise ValidationError(
                "The access request expired or its recipient is unavailable."
            )
        assignment_id = uuid4() if accept else None
        decision_id = uuid4()
        with (
            audited_mutation(
                guidance_authority_audit(
                    actor=actor,
                    organization_id=request.organization_id,
                    edition_id=request.edition_id,
                    operation="authorization.guidance.access.accept"
                    if accept
                    else "authorization.guidance.access.decline",
                    target_type="authorization.guidance_access_decision",
                    target_id=decision_id,
                    correlation_id=correlation_id,
                )
            ) as audit,
            _guidance_authority_writer(),
        ):
            GuidanceAccessDecision.objects.create(
                id=decision_id,
                request=request,
                actor=actor,
                accepted=accept,
                request_digest=expected_digest,
                assignment_id=assignment_id,
                source_audit_id=audit.audit_id,
                correlation_id=correlation_id,
            )
            if accept:
                assignment = RoleAssignment.objects.create(
                    id=assignment_id,
                    organization_id=request.organization_id,
                    edition_id=request.edition_id,
                    principal_id=request.recipient_id,
                    role_bundle_id=request.role_bundle_id,
                    effective_from=request.effective_from,
                    expires_at=request.expires_at,
                    granted_by_id=request.requested_by_id,
                    approved_by_id=request.approver_id,
                    reason=request.reason,
                )
                create_persistent_dual_control_issuance(
                    target=assignment,
                    actor_source=own_source,
                    approver_source=other_source,
                )
            _event(
                actor,
                request,
                "accepted" if accept else "declined",
                audit.audit_id,
                correlation_id,
            )
        return GuidanceAccessResult(request.id, assignment_id)


def revoke_guidance_access(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    assignment_id: UUID,
    reason: str,
    correlation_id: UUID,
) -> UUID:
    """Resolve purpose-qualified Guidance access.

    Remove one exact Guidance role with current purpose authority and retained
    evidence.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    organization_id : UUID
        Exact organization owning the requested scope.
    edition_id : UUID
        Exact event edition within the organization.
    assignment_id : UUID
        Exact existing Guidance assignment to revoke.
    reason : str
        Bounded accountable explanation, retained in private evidence.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    UUID
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    ValidationError
        If the immutable intent, version, acceptance or retained evidence conflicts.
    """
    _trace(organization_id, edition_id, assignment_id, correlation_id)
    reason = _reason(reason)
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        target = _scope(organization_id, edition_id, allow_read_only=True)
        now = timezone.now()
        source = _control(
            actor,
            target,
            role="actor",
            effective_from=now,
            expires_at=now + timedelta(microseconds=1),
        )
        assignment = (
            RoleAssignment.objects.select_for_update()
            .select_related("role_bundle")
            .filter(
                id=assignment_id,
                organization_id=organization_id,
                edition_id=edition_id,
                role_bundle__code__in=GUIDANCE_ROLE_RECIPES,
            )
            .first()
        )
        if assignment is None:
            raise PermissionDenied("Guidance access is unavailable.")
        existing = GuidanceRevocationReceipt.objects.filter(
            assignment=assignment
        ).first()
        if existing is not None:
            if existing.actor_id != actor.id or existing.reason != reason:
                raise ValidationError(
                    "This access was already removed with another retained decision."
                )
            return existing.id
        receipt_id = uuid4()
        with (
            audited_mutation(
                guidance_authority_audit(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    operation="authorization.guidance.access.revoke",
                    target_type="authorization.guidance_revocation_receipt",
                    target_id=receipt_id,
                    correlation_id=correlation_id,
                )
            ) as audit,
            _guidance_authority_writer(),
        ):
            GuidanceRevocationReceipt.objects.create(
                id=receipt_id,
                assignment=assignment,
                actor=actor,
                source=source,
                revoked_at=now,
                reason=reason,
                source_audit_id=audit.audit_id,
                correlation_id=correlation_id,
            )
            (
                assignment.revoked_at,
                assignment.revoked_by,
                assignment.revocation_reason,
            ) = now, actor, reason
            assignment.save(
                update_fields=(
                    "revoked_at",
                    "revoked_by",
                    "revocation_reason",
                    "updated_at",
                )
            )
            publish_guidance_authority_event(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                event_name="authorization.guidance_access.changed.v1",
                operation="revoked",
                aggregate_type="authorization.guidance_revocation_receipt",
                aggregate_id=receipt_id,
                correlation_id=correlation_id,
                audit_id=audit.audit_id,
            )
        return receipt_id
