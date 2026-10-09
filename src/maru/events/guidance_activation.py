"""Retain exact Guidance adoption decisions.

Accepted fresh Guidance responsibility and one explicit Announcements expansion
edge.
"""

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from maru.audit.mutation_evidence import audited_mutation
from maru.audit.services import AuditRecord
from maru.authorization.guidance_audit import (
    guidance_authority_audit,
    publish_guidance_authority_event,
)
from maru.authorization.guidance_authority_queries import (
    guidance_root_sources,
    guidance_team_reference,
)
from maru.authorization.guidance_bootstrap import establish_guidance_responsibilities
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.events.adoption import adoption_profile
from maru.events.guidance_activation_models import (
    GuidanceActivationDecision,
    GuidanceActivationReceipt,
    GuidanceActivationRequest,
)
from maru.events.guidance_activation_references import guidance_manifest_digest
from maru.events.guidance_setup_queries import require_guidance_setup_actor
from maru.events.guidance_setup_writer import _guidance_setup_writer
from maru.events.models import EventEdition
from maru.events.queries import resolve_edition_series_identity
from maru.identity.models import Account
from maru.identity.queries import (
    current_platform_administrator_is_available,
    resolve_active_verified_person_reference,
)
from maru.organizations.guidance_activation_references import (
    guidance_accountable_foundation,
)
from maru.organizations.write_references import lock_series_ownership

_MAX_RAW_REASON_LENGTH = 4096
_MAX_REASON_LENGTH = 240
_INDEPENDENT_PAIR_SIZE = 2

_GUIDANCE_REQUEST_LIFETIME = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class GuidanceActivationRequestResult:
    """Opaque original request identity, with a stable immutable preview version.

    Attributes
    ----------
    request_id : UUID
        Opaque identity of the retained immutable request.
    version : int
        Immutable request preview version required for an unchanged decision.
    replayed : bool
        Whether this result reuses the original completed command outcome.
    """

    request_id: UUID
    version: int = 1
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class GuidanceActivationResult:
    """Original retained result; replay never refreshes consent or repairs lineage.

    Attributes
    ----------
    request_id : UUID
        Opaque identity of the retained immutable request.
    receipt_id : UUID
        Original activation receipt retaining the accepted ceremony outcome.
    organization_id : UUID
        Exact organization owning this event and its evidence.
    edition_id : UUID
        Exact event edition within the owning organization.
    replayed : bool
        Whether this result reuses the original completed command outcome.
    """

    request_id: UUID
    receipt_id: UUID
    organization_id: UUID
    edition_id: UUID
    replayed: bool


def _trace(*values: UUID) -> None:
    if any(not isinstance(value, UUID) or value.int == 0 for value in values):
        raise ValidationError(
            "Use non-empty request identities.", code="guidance_activation_identity"
        )


def _reason(reason: str) -> str:
    if (
        not isinstance(reason, str)
        or len(reason) > _MAX_RAW_REASON_LENGTH
        or any(unicodedata.category(character).startswith("C") for character in reason)
    ):
        raise ValidationError("Enter a short responsibility reason.")
    result = " ".join(unicodedata.normalize("NFC", reason).split())
    if not result or len(result) > _MAX_REASON_LENGTH:
        raise ValidationError("Enter a reason of at most 240 characters.")
    return result


def _platform(actor: Account) -> None:
    require_guidance_setup_actor(actor)
    if not current_platform_administrator_is_available(account_id=actor.id, lock=True):
        raise PermissionDenied


def _lock_edition(organization_id: UUID, edition_id: UUID) -> EventEdition:
    series_id = resolve_edition_series_identity(
        organization_id=organization_id, edition_id=edition_id
    )
    if series_id is None or not lock_series_ownership(
        organization_id=organization_id, series_id=series_id
    ):
        raise PermissionDenied("The event is unavailable.")
    edition = (
        EventEdition.objects.select_for_update()
        .filter(id=edition_id, organization_id=organization_id, series_id=series_id)
        .first()
    )
    if edition is None:
        raise PermissionDenied("The event is unavailable.")
    return edition


def _live(edition: EventEdition) -> None:
    if (
        edition.organization.lifecycle != "active"
        or not edition.series.is_active
        or edition.lifecycle not in {"draft", "preparing", "ready", "live"}
    ):
        raise ValidationError("This event cannot start or recover Guidance now.")


def _pair(organization_id: UUID, operators: tuple[UUID, UUID]) -> None:
    if (
        len(operators) != _INDEPENDENT_PAIR_SIZE
        or operators[0] == operators[1]
        or not set(operators).issubset(
            {
                source.account_id
                for source in guidance_root_sources(
                    organization_id=organization_id, lock=True
                )
            }
        )
    ):
        raise PermissionDenied("Select two current accepted organization controllers.")


def _audit(
    actor: Account,
    request: GuidanceActivationRequest,
    operation: str,
    target_id: UUID,
    correlation_id: UUID,
) -> AuditRecord:
    return guidance_authority_audit(
        actor=actor,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        operation=f"events.guidance_adoption.{operation}",
        target_type="events.guidance_activation_request"
        if operation != "apply"
        else "events.guidance_activation_receipt",
        target_id=target_id,
        correlation_id=correlation_id,
        capability_code="events.create"
        if actor.is_platform_administrator
        else "organizations.manage_representation",
    )


def _event(
    actor: Account,
    request: GuidanceActivationRequest,
    operation: str,
    audit_id: UUID,
    correlation_id: UUID,
) -> None:
    publish_guidance_authority_event(
        actor=actor,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        event_name="events.guidance_adoption.changed.v1",
        operation=operation,
        aggregate_type="events.guidance_activation_request",
        aggregate_id=request.id,
        correlation_id=correlation_id,
        audit_id=audit_id,
    )


def propose_guidance_activation(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    expected_edition_version: int,
    operator_ids: tuple[UUID, UUID],
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
) -> GuidanceActivationRequestResult:
    """Retain the exact accepted Guidance responsibility.

    Freeze one normalized preview; collecting consent grants no operational
    access.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    organization_id : UUID
        Exact organization owning the requested scope.
    edition_id : UUID
        Exact event edition within the organization.
    expected_edition_version : int
        Exact edition version shown by the original preview.
    operator_ids : tuple[UUID, UUID]
        The two current accepted organization-root holders named in the plan.
    reason : str
        Bounded accountable explanation, retained in private evidence.
    idempotency_key : UUID
        Stable key for the original intent; changed details are rejected.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    GuidanceActivationRequestResult
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    ValidationError
        If the immutable intent, version, acceptance or retained evidence conflicts.
    """
    require_guidance_setup_actor(actor)
    _trace(organization_id, edition_id, idempotency_key, correlation_id, *operator_ids)
    if (
        isinstance(expected_edition_version, bool)
        or not isinstance(expected_edition_version, int)
        or expected_edition_version < 1
        or len(operator_ids) != _INDEPENDENT_PAIR_SIZE
    ):
        raise ValidationError("Use the current event and two selected people.")
    reason = _reason(reason)
    ordered_operators = sorted(operator_ids, key=str)
    operators = (ordered_operators[0], ordered_operators[1])
    digest = hashlib.sha256(
        json.dumps(
            [
                str(organization_id),
                str(edition_id),
                expected_edition_version,
                [str(person) for person in operators],
                reason,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                [
                    int.from_bytes(
                        hashlib.sha256(
                            actor.id.bytes
                            + idempotency_key.bytes
                            + b"guidance-activation"
                        ).digest()[:8],
                        "big",
                        signed=True,
                    )
                ],
            )
        existing = GuidanceActivationRequest.objects.filter(
            proposed_by_id=actor.id, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            _platform(actor)
            if existing.request_digest != digest:
                raise ValidationError(
                    "This request key already describes different responsibilities."
                )
            return GuidanceActivationRequestResult(existing.id, replayed=True)
        edition = _lock_edition(organization_id, edition_id)
        _platform(actor)
        _live(edition)
        if edition.aggregate_version != expected_edition_version:
            raise ValidationError("The event changed. Review the current setup again.")
        source = adoption_profile(
            edition.adoption_profile_code, edition.adoption_profile_version
        )
        target_code = (
            "announcements_guidance"
            if edition.adoption_profile_code == "announcements_only"
            else edition.adoption_profile_code
        )
        target = adoption_profile(target_code, 1)
        if (
            source is None
            or source.key
            not in {
                ("announcements_only", 1),
                ("guidance_only", 1),
                ("announcements_guidance", 1),
            }
            or target is None
        ):
            raise ValidationError(
                "This event does not support the accepted Guidance adoption edge."
            )
        foundation = guidance_accountable_foundation(
            organization_id=organization_id, for_update=True
        )
        _pair(organization_id, operators)
        if foundation is None:
            raise PermissionDenied
        team = guidance_team_reference(
            organization_id=organization_id, edition_id=edition_id
        )
        if team is not None and team.ready:
            raise ValidationError("Guidance already has its accepted current team.")
        request = GuidanceActivationRequest(
            organization_id=organization_id,
            edition=edition,
            representation_id=foundation.representation_id,
            proposed_by=actor,
            operator_a_id=operators[0],
            operator_b_id=operators[1],
            idempotency_key=idempotency_key,
            request_digest=digest,
            expected_edition_version=expected_edition_version,
            expected_adoption_revision=edition.adoption_revision,
            source_profile_code=source.code,
            source_profile_version=source.version,
            target_profile_code=target.code,
            target_profile_version=target.version,
            source_manifest_digest=guidance_manifest_digest(source),
            target_manifest_digest=guidance_manifest_digest(target),
            representation_version=foundation.representation_version,
            purpose="recovery" if team else "initial",
            reason=reason,
            expires_at=timezone.now() + _GUIDANCE_REQUEST_LIFETIME,
            correlation_id=correlation_id,
        )
        with (
            audited_mutation(
                _audit(actor, request, "propose", request.id, correlation_id)
            ) as audit,
            _guidance_setup_writer(),
        ):
            request.source_audit_id = audit.audit_id
            request.save(force_insert=True)
            _event(actor, request, "proposed", audit.audit_id, correlation_id)
        return GuidanceActivationRequestResult(request.id)


def _current_request(request: GuidanceActivationRequest, edition: EventEdition) -> None:
    _live(edition)
    foundation = guidance_accountable_foundation(
        organization_id=request.organization_id, for_update=True
    )
    if (
        foundation is None
        or foundation.representation_id != request.representation_id
        or foundation.representation_version != request.representation_version
        or edition.aggregate_version != request.expected_edition_version
        or edition.adoption_revision != request.expected_adoption_revision
        or (edition.adoption_profile_code, edition.adoption_profile_version)
        != (request.source_profile_code, request.source_profile_version)
        or request.expires_at <= timezone.now()
    ):
        raise ValidationError(
            "The responsibility plan changed or expired. Start a fresh request."
        )
    _pair(request.organization_id, (request.operator_a_id, request.operator_b_id))
    source = adoption_profile(
        request.source_profile_code, request.source_profile_version
    )
    target = adoption_profile(
        request.target_profile_code, request.target_profile_version
    )
    if (
        source is None
        or target is None
        or guidance_manifest_digest(source) != request.source_manifest_digest
        or guidance_manifest_digest(target) != request.target_manifest_digest
    ):
        raise ValidationError(
            "The exact workspace contract changed. Review a fresh request."
        )


def respond_to_guidance_activation(
    *,
    actor: Account,
    request_id: UUID,
    expected_version: int,
    accept: bool,
    correlation_id: UUID,
) -> GuidanceActivationRequestResult:
    """Retain actual self-acceptance and approval of the other person's exact plan.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    request_id : UUID
        Opaque identifier of the original immutable request.
    expected_version : int
        Original immutable responsibility preview version.
    accept : bool
        The actual named person's authenticated acceptance or refusal.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    GuidanceActivationRequestResult
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    ValidationError
        If the immutable intent, version, acceptance or retained evidence conflicts.
    """
    from maru.events.guidance_setup_readiness import (  # noqa: PLC0415
        require_guidance_setup_integrity,
    )

    require_guidance_setup_integrity()
    _trace(request_id, correlation_id)
    if (
        expected_version != 1
        or isinstance(expected_version, bool)
        or not isinstance(accept, bool)
    ):
        raise ValidationError("Use the original responsibility preview.")
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        locator = (
            GuidanceActivationRequest.objects.filter(
                Q(operator_a_id=actor.id) | Q(operator_b_id=actor.id),
                id=request_id,
            )
            .values("organization_id", "edition_id")
            .first()
        )
        if locator is None:
            raise PermissionDenied
        edition = _lock_edition(locator["organization_id"], locator["edition_id"])
        if resolve_active_verified_person_reference(
            account_id=actor.id, lock=True
        ) is None or actor.id not in {
            source.account_id
            for source in guidance_root_sources(
                organization_id=locator["organization_id"], lock=True
            )
        }:
            raise PermissionDenied
        request = GuidanceActivationRequest.objects.get(id=request_id)
        _pair(request.organization_id, (request.operator_a_id, request.operator_b_id))
        existing = GuidanceActivationDecision.objects.filter(
            request=request, actor=actor
        ).first()
        if existing is not None:
            if (
                existing.accepted != accept
                or existing.request_digest != request.request_digest
            ):
                raise ValidationError(
                    "Your answer to this exact request is already retained."
                )
            return GuidanceActivationRequestResult(request.id, replayed=True)
        _current_request(request, edition)
        if request.decisions.filter(accepted=False).exists():
            raise ValidationError("This request was declined. Start a fresh request.")
        with (
            audited_mutation(
                _audit(
                    actor,
                    request,
                    "accept" if accept else "decline",
                    request.id,
                    correlation_id,
                )
            ) as audit,
            _guidance_setup_writer(),
        ):
            GuidanceActivationDecision.objects.create(
                request=request,
                actor=actor,
                accepted=accept,
                request_digest=request.request_digest,
                source_audit_id=audit.audit_id,
                correlation_id=correlation_id,
            )
            _event(
                actor,
                request,
                "accepted" if accept else "declined",
                audit.audit_id,
                correlation_id,
            )
        return GuidanceActivationRequestResult(request.id)


def apply_guidance_activation(
    *, actor: Account, request_id: UUID, expected_version: int, correlation_id: UUID
) -> GuidanceActivationResult:
    """Retain the exact accepted Guidance responsibility.

    Recheck the actual decisions and atomically preserve the event while issuing
    access.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    request_id : UUID
        Opaque identifier of the original immutable request.
    expected_version : int
        Original immutable responsibility preview version.
    correlation_id : UUID
        Non-empty audit trace for this attempt.

    Returns
    -------
    GuidanceActivationResult
        The admitted immutable result; it grants no additional authority.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    ValidationError
        If the immutable intent, version, acceptance or retained evidence conflicts.
    """
    require_guidance_setup_actor(actor)
    from maru.events.guidance_setup_readiness import (  # noqa: PLC0415
        require_guidance_setup_integrity,
    )

    require_guidance_setup_integrity()
    _trace(request_id, correlation_id)
    if expected_version != 1 or isinstance(expected_version, bool):
        raise ValidationError("Use the original responsibility preview.")
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        request = GuidanceActivationRequest.objects.filter(
            id=request_id, proposed_by_id=actor.id
        ).first()
        if request is None:
            raise PermissionDenied
        edition = _lock_edition(request.organization_id, request.edition_id)
        request = GuidanceActivationRequest.objects.get(id=request_id)
        _platform(actor)
        existing = GuidanceActivationReceipt.objects.filter(request=request).first()
        if existing is not None:
            return GuidanceActivationResult(
                request.id,
                existing.id,
                request.organization_id,
                request.edition_id,
                replayed=True,
            )
        _current_request(request, edition)
        answers = tuple(
            request.decisions.values_list("actor_id", "accepted", "request_digest")
        )
        if (
            len(answers) != _INDEPENDENT_PAIR_SIZE
            or {row[0] for row in answers}
            != {request.operator_a_id, request.operator_b_id}
            or any(not row[1] or row[2] != request.request_digest for row in answers)
        ):
            raise ValidationError(
                "Both named people must accept this exact responsibility plan first."
            )
        receipt_id = uuid4()
        with (
            audited_mutation(
                _audit(actor, request, "apply", receipt_id, correlation_id)
            ) as audit,
            _guidance_setup_writer(),
        ):
            receipt = GuidanceActivationReceipt.objects.create(
                id=receipt_id,
                request=request,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                applied_by=actor,
                source_audit_id=audit.audit_id,
                result_edition_version=edition.aggregate_version + 1,
                result_adoption_revision=edition.adoption_revision + 1,
                correlation_id=correlation_id,
            )
            updated = EventEdition.objects.filter(
                id=edition.id,
                aggregate_version=request.expected_edition_version,
                adoption_revision=request.expected_adoption_revision,
            ).update(
                adoption_profile_code=request.target_profile_code,
                adoption_profile_version=request.target_profile_version,
                aggregate_version=receipt.result_edition_version,
                adoption_revision=receipt.result_adoption_revision,
                updated_at=timezone.now(),
            )
            if updated != 1:
                raise ValidationError("The event changed during setup; start again.")
            establish_guidance_responsibilities(activation_id=receipt.id)
            _event(
                actor,
                request,
                "recovered" if request.purpose == "recovery" else "activated",
                audit.audit_id,
                correlation_id,
            )
        return GuidanceActivationResult(
            request.id,
            receipt.id,
            request.organization_id,
            request.edition_id,
            replayed=False,
        )
