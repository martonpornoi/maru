"""Authorized workforce applications, documents, and position assignments."""

from __future__ import annotations

import hashlib
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.commands import assign_role
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    decide,
    resolve_edition_target,
    resolve_owned_target,
    resolve_self_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.identity.models import Account
from maru.participation.models import Participation, ParticipationCapacity
from maru.workforce.edition_write_scope import (
    lock_active_department_write_target,
    lock_workforce_edition_write_scope,
)
from maru.workforce.models import (
    MAX_ONBOARDING_DOCUMENT_BYTES,
    OnboardingDocumentRequest,
    Position,
    PositionAssignment,
    VolunteerApplication,
    VolunteerOpportunity,
)

VIEW_SELF = "workforce.view_self"
APPLY_SELF = "workforce.apply_self"
MANAGE_DOCUMENTS = "workforce.manage_documents"
MANAGE_ASSIGNMENTS = "workforce.manage_assignments"
PDF_CONTENT_TYPE = "application/pdf"
PDF_SIGNATURE = b"%PDF-"
CLAMAV_CHUNK_SIZE = 64 * 1024


class ReadableUpload(Protocol):
    name: str | None
    content_type: str | None

    def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    content: ContentFile[bytes]
    original_filename: str
    content_type: str
    byte_count: int
    sha256: str
    scanner_code: str


def _require(
    *,
    actor: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget | None,
) -> frozenset[str]:
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=target,
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "The workforce operation is unavailable.",
            reason_code=decision.reason_code,
        )
    return decision.obligations


def _audit(
    *,
    actor: Account,
    capability_code: str,
    operation: str,
    organization_id: UUID,
    edition_id: UUID,
    target_type: str,
    target_id: UUID,
    correlation_id: UUID,
    reason_code: str,
    authorization_target: ResolvedAuthorizationTarget | None,
    changed_fields: tuple[str, ...] = (),
    source_channel: str = "api",
) -> AuditEvent:
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(
                sorted(
                    _require(
                        actor=actor,
                        capability_code=capability_code,
                        target=authorization_target,
                    )
                )
            ),
            changed_fields=changed_fields,
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="workforce-operational",
        )
    )


def _clamav_scan(data: bytes) -> str:
    host = settings.MARU_MEDIA_SCANNER_HOST
    port = settings.MARU_MEDIA_SCANNER_PORT
    if not host:
        raise ValidationError(
            "Document scanning is unavailable.",
            code="document_scanner_unavailable",
        )
    try:
        with socket.create_connection(
            (host, port),
            timeout=settings.MARU_MEDIA_SCANNER_TIMEOUT_SECONDS,
        ) as connection:
            connection.sendall(b"zINSTREAM\0")
            for offset in range(0, len(data), CLAMAV_CHUNK_SIZE):
                chunk = data[offset : offset + CLAMAV_CHUNK_SIZE]
                connection.sendall(len(chunk).to_bytes(4, "big") + chunk)
            connection.sendall((0).to_bytes(4, "big"))
            response = connection.recv(4096)
    except OSError as error:
        raise ValidationError(
            "Document scanning is temporarily unavailable.",
            code="document_scanner_unavailable",
        ) from error
    if b" FOUND" in response:
        raise ValidationError(
            "The uploaded document was rejected by the safety scanner.",
            code="document_malware_detected",
        )
    if b" OK" not in response:
        raise ValidationError(
            "Document scanning did not return a safe result.",
            code="document_scanner_uncertain",
        )
    return "clamav_clean"


def process_pdf(upload: ReadableUpload, *, max_bytes: int) -> ProcessedDocument:
    """Bound and scan one PDF without interpreting or rendering its contents."""

    effective_limit = min(max_bytes, MAX_ONBOARDING_DOCUMENT_BYTES)
    data = upload.read(effective_limit + 1)
    if len(data) > effective_limit:
        raise ValidationError(
            f"Use a PDF no larger than {effective_limit // (1024 * 1024)} MB.",
            code="document_file_too_large",
        )
    if upload.content_type != PDF_CONTENT_TYPE or not data.startswith(PDF_SIGNATURE):
        raise ValidationError(
            "Upload a PDF document.",
            code="document_type_invalid",
        )
    scanner = settings.MARU_MEDIA_SCANNER
    if scanner == "test_clean" and not settings.DEBUG:
        scanner_code = "test_clean"
    elif scanner == "local_rehearsal_clean" and settings.DEBUG:
        scanner_code = "local_rehearsal_clean_unscanned"
    elif scanner == "clamav":
        scanner_code = _clamav_scan(data)
    else:
        raise ValidationError(
            "Document uploads are disabled until a malware scanner is configured.",
            code="document_scanner_unavailable",
        )
    supplied_name = upload.name or "signed-document.pdf"
    filename = supplied_name.rsplit("/", maxsplit=1)[-1].rsplit("\\", maxsplit=1)[-1]
    return ProcessedDocument(
        content=ContentFile(data, name="signed-document.pdf"),
        original_filename=filename[:255],
        content_type=PDF_CONTENT_TYPE,
        byte_count=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        scanner_code=scanner_code,
    )


def submit_volunteer_application(
    *,
    actor: Account,
    opportunity_id: UUID,
    motivation: str,
    correlation_id: UUID,
    now: datetime | None = None,
) -> VolunteerApplication:
    normalized_motivation = motivation.strip()
    if not normalized_motivation:
        raise ValidationError(
            {"motivation": "Tell the organizers why this position interests you."},
            code="application_motivation_required",
        )
    submitted_at = now or timezone.now()
    with transaction.atomic():
        opportunity = (
            VolunteerOpportunity.objects.select_for_update()
            .select_related("position")
            .get(id=opportunity_id)
        )
        position = opportunity.position
        if not actor.is_active:
            raise ValidationError(
                "This opportunity is not accepting applications.",
                code="opportunity_not_accepting",
            )
        _require(
            actor=actor,
            capability_code=APPLY_SELF,
            target=resolve_self_target(
                principal=actor,
                organization_id=position.organization_id,
                edition_id=position.edition_id,
            ),
        )
        if not opportunity.accepts_applications:
            raise ValidationError(
                "This opportunity is not accepting applications.",
                code="opportunity_not_accepting",
            )
        application = VolunteerApplication.objects.create(
            opportunity=opportunity,
            account=actor,
            motivation=normalized_motivation,
            submitted_at=submitted_at,
        )
        audit = _audit(
            actor=actor,
            capability_code=APPLY_SELF,
            operation="workforce.application.submit",
            organization_id=position.organization_id,
            edition_id=position.edition_id,
            target_type="workforce.volunteer_application",
            target_id=application.id,
            correlation_id=correlation_id,
            reason_code="self_relationship",
            authorization_target=resolve_owned_target(resource=application),
            changed_fields=("application",),
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="workforce.application.submitted.v1",
                schema_version=1,
                organization_id=position.organization_id,
                event_edition_id=position.edition_id,
                aggregate_type="workforce.volunteer_application",
                aggregate_id=application.id,
                aggregate_version=1,
                payload={"position_code": position.code, "status": application.status},
                correlation_id=correlation_id,
                causation_id=audit.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="workforce-operational",
            ),
            workload_pool="core",
        )
        return application


def upload_onboarding_document(
    *,
    actor: Account,
    request_id: UUID,
    upload: ReadableUpload,
    correlation_id: UUID,
) -> OnboardingDocumentRequest:
    with transaction.atomic():
        document_request = (
            OnboardingDocumentRequest.objects.select_for_update()
            .select_related("document_type")
            .get(id=request_id, account=actor)
        )
        _require(
            actor=actor,
            capability_code=VIEW_SELF,
            target=resolve_owned_target(resource=document_request),
        )
        if document_request.status not in {
            OnboardingDocumentRequest.Status.REQUESTED,
            OnboardingDocumentRequest.Status.REJECTED,
        }:
            raise ValidationError(
                "This document request is not accepting another upload.",
                code="document_request_not_uploadable",
            )
        processed = process_pdf(
            upload,
            max_bytes=document_request.document_type.max_bytes,
        )
        old_storage_name = document_request.document.name
        document_request.document = processed.content
        document_request.original_filename = processed.original_filename
        document_request.content_type = processed.content_type
        document_request.byte_count = processed.byte_count
        document_request.sha256 = processed.sha256
        document_request.scanner_code = processed.scanner_code
        document_request.status = OnboardingDocumentRequest.Status.SUBMITTED
        document_request.submitted_at = timezone.now()
        document_request.reviewed_by = None
        document_request.reviewed_at = None
        document_request.review_reason = ""
        document_request.save()
        if (
            old_storage_name
            and old_storage_name != document_request.document.name
            and default_storage.exists(old_storage_name)
        ):
            transaction.on_commit(lambda: default_storage.delete(old_storage_name))
        _audit(
            actor=actor,
            capability_code=VIEW_SELF,
            operation="workforce.document.upload",
            organization_id=document_request.organization_id,
            edition_id=document_request.edition_id,
            target_type="workforce.onboarding_document_request",
            target_id=document_request.id,
            correlation_id=correlation_id,
            reason_code="self_relationship",
            authorization_target=resolve_owned_target(resource=document_request),
            changed_fields=("document", "status", "safety_receipt"),
        )
        return document_request


def review_onboarding_document(
    *,
    actor: Account,
    request_id: UUID,
    decision: str,
    reason: str,
    correlation_id: UUID,
) -> OnboardingDocumentRequest:
    normalized_reason = reason.strip()
    if decision not in {
        OnboardingDocumentRequest.Status.APPROVED,
        OnboardingDocumentRequest.Status.REJECTED,
    }:
        raise ValidationError(
            "Choose approve or reject.",
            code="review_decision_invalid",
        )
    if not normalized_reason:
        raise ValidationError(
            {"review_reason": "A review reason is required."},
            code="review_reason_required",
        )
    with transaction.atomic():
        document_request = (
            OnboardingDocumentRequest.objects.select_for_update()
            .select_related("document_type")
            .get(id=request_id)
        )
        _require(
            actor=actor,
            capability_code=MANAGE_DOCUMENTS,
            target=resolve_owned_target(resource=document_request),
        )
        if document_request.status != OnboardingDocumentRequest.Status.SUBMITTED:
            raise ValidationError(
                "Only a submitted document can be reviewed.",
                code="document_not_submitted",
            )
        document_request.status = decision
        document_request.reviewed_by = actor
        document_request.reviewed_at = timezone.now()
        document_request.review_reason = normalized_reason
        document_request.save(
            update_fields=(
                "status",
                "reviewed_by",
                "reviewed_at",
                "review_reason",
                "updated_at",
            )
        )
        audit = _audit(
            actor=actor,
            capability_code=MANAGE_DOCUMENTS,
            operation="workforce.document.review",
            organization_id=document_request.organization_id,
            edition_id=document_request.edition_id,
            target_type="workforce.onboarding_document_request",
            target_id=document_request.id,
            correlation_id=correlation_id,
            reason_code=f"document_{decision}",
            authorization_target=resolve_owned_target(resource=document_request),
            changed_fields=("status", "review_evidence"),
            source_channel="admin",
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="workforce.document.reviewed.v1",
                schema_version=1,
                organization_id=document_request.organization_id,
                event_edition_id=document_request.edition_id,
                aggregate_type="workforce.onboarding_document_request",
                aggregate_id=document_request.id,
                aggregate_version=2,
                payload={
                    "document_type_code": document_request.document_type.code,
                    "decision": decision,
                },
                correlation_id=correlation_id,
                causation_id=audit.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="workforce-restricted",
            ),
            workload_pool="core",
        )
        return document_request


def activate_position_assignment(  # noqa: PLR0912, PLR0915
    *,
    position_id: UUID,
    account: Account,
    actor: Account,
    approver: Account,
    effective_from: datetime,
    expires_at: datetime | None,
    reason: str,
    correlation_id: UUID,
    proposed_assignment_id: UUID | None = None,
) -> PositionAssignment:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError({"reason": "An assignment reason is required."})
    if actor.id == approver.id:
        raise ValidationError(
            {"approved_by": "A different controller must approve this assignment."}
        )
    with transaction.atomic():
        position_reference = (
            Position.objects.filter(id=position_id)
            .order_by()
            .values_list(
                "organization_id",
                "edition__series_id",
                "edition_id",
                "department_id",
            )
            .first()
        )
        if position_reference is None:
            raise ValidationError(
                "The workforce Position target is unavailable.",
                code="workforce_position_unavailable",
            )
        organization_id, series_id, edition_id, department_id = position_reference
        write_scope = lock_workforce_edition_write_scope(
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        lock_active_department_write_target(
            scope=write_scope,
            department_id=department_id,
        )
        position = (
            Position.objects.select_for_update()
            .select_related("role_bundle", "edition", "department")
            .filter(
                id=position_id,
                organization_id=write_scope.organization_id,
                edition_id=write_scope.edition_id,
                department_id=department_id,
            )
            .order_by()
            .first()
        )
        if position is None:
            raise ValidationError(
                "The workforce Position target is unavailable.",
                code="workforce_position_unavailable",
            )
        for controller in (actor, approver):
            _require(
                actor=controller,
                capability_code=MANAGE_ASSIGNMENTS,
                target=resolve_edition_target(
                    organization_id=position.organization_id,
                    edition_id=position.edition_id,
                ),
            )
        if position.status == Position.Status.CLOSED:
            raise ValidationError(
                "A closed position cannot receive assignments.",
                code="position_closed",
            )
        active_assignment_ids = tuple(
            PositionAssignment.objects.select_for_update()
            .filter(
                position=position,
                status=PositionAssignment.Status.ACTIVE,
            )
            .order_by("id")
            .values_list("id", flat=True)
        )
        active_count = len(active_assignment_ids)
        if active_count >= position.headcount:
            raise ValidationError(
                "This position has reached its approved headcount.",
                code="position_headcount_reached",
            )
        proposed_assignment: PositionAssignment | None = None
        if proposed_assignment_id is not None:
            proposed_assignment = (
                PositionAssignment.objects.select_for_update()
                .filter(
                    id=proposed_assignment_id,
                    position=position,
                    organization_id=write_scope.organization_id,
                    edition_id=write_scope.edition_id,
                    account=account,
                    status=PositionAssignment.Status.PROPOSED,
                )
                .order_by()
                .first()
            )
            if proposed_assignment is None:
                raise ValidationError(
                    "The proposed workforce assignment is unavailable.",
                    code="workforce_assignment_unavailable",
                )
        required_type_ids = set(
            position.document_requirements.values_list("document_type_id", flat=True)
        )
        approved_type_ids = set(
            OnboardingDocumentRequest.objects.filter(
                organization_id=position.organization_id,
                edition_id=position.edition_id,
                account=account,
                document_type_id__in=required_type_ids,
                status=OnboardingDocumentRequest.Status.APPROVED,
            ).values_list("document_type_id", flat=True)
        )
        if required_type_ids != approved_type_ids:
            raise ValidationError(
                "Every required onboarding document must be approved first.",
                code="assignment_documents_incomplete",
            )
        assignment_target = resolve_edition_target(
            organization_id=position.organization_id,
            edition_id=position.edition_id,
        )
        if assignment_target is None:
            raise AuthorizationDenied(
                "The workforce operation is unavailable.",
                reason_code="target_unavailable",
            )
        role_assignment = assign_role(
            actor=actor,
            approver=approver,
            recipient=account,
            target=assignment_target,
            role_bundle_id=position.role_bundle_id,
            effective_from=effective_from,
            expires_at=expires_at,
            reason=normalized_reason,
            correlation_id=correlation_id,
            source_channel="workforce",
        )
        participation, _ = Participation.objects.get_or_create(
            organization_id=position.organization_id,
            edition_id=position.edition_id,
            account=account,
            defaults={
                "status": Participation.Status.ACTIVE,
                "edition_name_snapshot": position.edition.name,
                "series_name_snapshot": position.edition.series.name,
            },
        )
        if participation.status in {
            Participation.Status.INTERESTED,
            Participation.Status.PENDING,
            Participation.Status.CONFIRMED,
        }:
            participation.status = Participation.Status.ACTIVE
            participation.save(update_fields=("status", "updated_at"))
        for capacity_code in position.capacity_codes:
            label = {
                "volunteer": "Volunteer",
                "staff": "Staff",
            }.get(capacity_code, position.title)
            capacity, created = ParticipationCapacity.objects.get_or_create(
                participation=participation,
                code=capacity_code,
                defaults={
                    "label_snapshot": label,
                    "status": ParticipationCapacity.Status.ACTIVE,
                    "contribution_summary": position.description[:240],
                    "started_at": effective_from,
                },
            )
            if not created and capacity.status != ParticipationCapacity.Status.ACTIVE:
                capacity.status = ParticipationCapacity.Status.ACTIVE
                capacity.label_snapshot = label
                capacity.contribution_summary = position.description[:240]
                capacity.started_at = effective_from
                capacity.ended_at = None
                capacity.save(
                    update_fields=(
                        "status",
                        "label_snapshot",
                        "contribution_summary",
                        "started_at",
                        "ended_at",
                        "updated_at",
                    )
                )
        specific_code = f"position.{position.code}"
        position_capacity, created = ParticipationCapacity.objects.get_or_create(
            participation=participation,
            code=specific_code,
            defaults={
                "label_snapshot": position.title,
                "status": ParticipationCapacity.Status.ACTIVE,
                "contribution_summary": position.description[:240],
                "started_at": effective_from,
            },
        )
        if (
            not created
            and position_capacity.status != ParticipationCapacity.Status.ACTIVE
        ):
            position_capacity.status = ParticipationCapacity.Status.ACTIVE
            position_capacity.started_at = effective_from
            position_capacity.ended_at = None
            position_capacity.save(
                update_fields=("status", "started_at", "ended_at", "updated_at")
            )
        if proposed_assignment_id is None:
            assignment = PositionAssignment.objects.create(
                position=position,
                organization_id=position.organization_id,
                edition_id=position.edition_id,
                account=account,
                status=PositionAssignment.Status.ACTIVE,
                effective_from=effective_from,
                expires_at=expires_at,
                proposed_by=actor,
                approved_by=approver,
                reason=normalized_reason,
                role_assignment=role_assignment,
                participation_capacity=position_capacity,
            )
        else:
            if proposed_assignment is None:
                raise ValidationError(
                    "The proposed workforce assignment is unavailable.",
                    code="workforce_assignment_unavailable",
                )
            assignment = proposed_assignment
            assignment.status = PositionAssignment.Status.ACTIVE
            assignment.effective_from = effective_from
            assignment.expires_at = expires_at
            assignment.approved_by = approver
            assignment.reason = normalized_reason
            assignment.role_assignment = role_assignment
            assignment.participation_capacity = position_capacity
            assignment.save()
        new_active_count = active_count + 1
        position.status = (
            Position.Status.FILLED
            if new_active_count >= position.headcount
            else Position.Status.OPEN
        )
        position.save(update_fields=("status", "updated_at"))
        audit = _audit(
            actor=actor,
            capability_code=MANAGE_ASSIGNMENTS,
            operation="workforce.position_assignment.activate",
            organization_id=position.organization_id,
            edition_id=position.edition_id,
            target_type="workforce.position_assignment",
            target_id=assignment.id,
            correlation_id=correlation_id,
            reason_code="assignment_activated",
            authorization_target=resolve_owned_target(resource=assignment),
            changed_fields=("assignment", "role_assignment", "participation_capacity"),
            source_channel="admin",
        )
        _audit(
            actor=approver,
            capability_code=MANAGE_ASSIGNMENTS,
            operation="workforce.position_assignment.approve",
            organization_id=position.organization_id,
            edition_id=position.edition_id,
            target_type="workforce.position_assignment",
            target_id=assignment.id,
            correlation_id=correlation_id,
            reason_code="independent_approval",
            authorization_target=resolve_owned_target(resource=assignment),
            changed_fields=("assignment_approval",),
            source_channel="admin",
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="workforce.position_assignment.activated.v1",
                schema_version=1,
                organization_id=position.organization_id,
                event_edition_id=position.edition_id,
                aggregate_type="workforce.position_assignment",
                aggregate_id=assignment.id,
                aggregate_version=1,
                payload={
                    "position_code": position.code,
                    "role_code": position.role_bundle.code,
                    "status": assignment.status,
                },
                correlation_id=correlation_id,
                causation_id=audit.id,
                actor_kind="account",
                actor_id=actor.id,
                retention_class="workforce-operational",
            ),
            workload_pool="core",
        )
        return assignment
