"""Scoped, dual-controlled access sharing for the Management Console."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast
from uuid import UUID

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION, capability
from maru.authorization.commands import (
    assign_role,
    revoke_role_assignment,
)
from maru.authorization.models import RoleAssignment, RoleBundle
from maru.authorization.policy import ResourceScope, decide
from maru.authorization.serializers import (
    AccessAssignmentCreateSerializer,
    AccessAssignmentReplaceSerializer,
    AccessAssignmentRevokeSerializer,
    AccessWorkspaceSerializer,
)
from maru.events.models import EventEdition
from maru.identity.models import Account

MANAGE_ACCESS_CAPABILITY = "authorization.manage_roles"
ACCESS_GROUP_LABELS = {
    "board-member": "Board",
    "registration-lead": "Registration",
}
NON_SHAREABLE_ROLE_CODES = frozenset({"authority-controller"})


def _correlation_id(request: Request) -> UUID:
    return UUID(request.correlation_id)  # type: ignore[attr-defined]


def _account(request: Request) -> Account:
    account = request.user
    if not isinstance(account, Account):
        raise TypeError("Authenticated principal is not a platform account")
    return account


def _audit_access_workspace(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    outcome: str,
    reason_code: str,
    target_count: int | None = None,
) -> None:
    safe_metadata: dict[str, object] = {"policy_version": POLICY_VERSION}
    if target_count is not None:
        safe_metadata["target_count"] = target_count
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=account.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=MANAGE_ACCESS_CAPABILITY,
            operation="authorization.access_workspace.view",
            target_type="authorization.role_assignment",
            target_id=None,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="management-console",
            obligations=("audit_sensitive_read",),
            safe_metadata=safe_metadata,
            retention_class="security-extended",
        )
    )


def _authorize_access(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    audit_read: bool,
) -> None:
    decision = decide(
        principal=account,
        capability_code=MANAGE_ACCESS_CAPABILITY,
        resource=ResourceScope(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        if audit_read:
            _audit_access_workspace(
                account=account,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=decision.reason_code,
            )
        raise PermissionDenied("Access management is unavailable for this workspace.")


def _edition(*, organization_id: UUID, edition_id: UUID) -> EventEdition:
    edition = (
        EventEdition.objects.select_related("organization")
        .filter(pk=edition_id, organization_id=organization_id)
        .first()
    )
    if edition is None:
        raise NotFound("The convention workspace is unavailable.")
    return edition


def _latest_roles(organization_id: UUID) -> list[RoleBundle]:
    roles = (
        RoleBundle.objects.filter(organization_id=organization_id)
        .exclude(code__in=NON_SHAREABLE_ROLE_CODES)
        .order_by("code", "-version", "id")
    )
    latest: dict[str, RoleBundle] = {}
    for role in roles:
        latest.setdefault(role.code, role)
    return sorted(
        latest.values(),
        key=lambda role: _group_name(role).casefold(),
    )


def _group_name(role: RoleBundle) -> str:
    return ACCESS_GROUP_LABELS.get(role.code, role.name)


def _capability_label(code: str) -> str:
    domain, _, action = code.partition(".")
    return f"{domain.replace('_', ' ').title()} · {action.replace('_', ' ').title()}"


def _group_payload(role: RoleBundle) -> dict[str, object]:
    capabilities: list[dict[str, str]] = []
    for code in role.capability_codes:
        definition = capability(code)
        if definition is None:
            continue
        capabilities.append(
            {
                "code": code,
                "label": _capability_label(code),
                "description": definition.description,
            }
        )
    description = (
        capabilities[0]["description"]
        if capabilities
        else "Provides convention access defined by this role."
    )
    return {
        "code": role.code,
        "name": _group_name(role),
        "description": description,
        "capability_count": len(capabilities),
        "capabilities": capabilities,
    }


def _assignment_status(assignment: RoleAssignment) -> str:
    now = timezone.now()
    if assignment.effective_from > now:
        return "Scheduled"
    if assignment.expires_at is not None and assignment.expires_at <= now:
        return "Expired"
    return "Active"


def _assignment_payload(
    assignment: RoleAssignment,
    *,
    edition: EventEdition,
) -> dict[str, object]:
    return {
        "id": assignment.id,
        "person_display_name": assignment.principal.display_name,
        "person_email": assignment.principal.email,
        "group_code": assignment.role_bundle.code,
        "group_name": _group_name(assignment.role_bundle),
        "scope_label": (
            edition.name
            if assignment.edition_id
            else f"{edition.organization.name} · all editions"
        ),
        "status": _assignment_status(assignment),
        "effective_from": assignment.effective_from,
        "expires_at": assignment.expires_at,
        "granted_by_name": (
            assignment.granted_by.display_name
            if assignment.granted_by is not None
            else "Bootstrap authority"
        ),
        "approved_by_name": (
            assignment.approved_by.display_name
            if assignment.approved_by is not None
            else "Bootstrap authority"
        ),
    }


def _current_assignments(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> Iterable[RoleAssignment]:
    now = timezone.now()
    return (
        RoleAssignment.objects.filter(
            Q(edition_id=edition_id) | Q(edition__isnull=True),
            organization_id=organization_id,
            revoked_at__isnull=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .select_related(
            "principal",
            "role_bundle",
            "granted_by",
            "approved_by",
        )
        .order_by(
            "role_bundle__name",
            "principal__display_name",
            "principal__email",
        )
    )


def _workspace_payload(
    *,
    edition: EventEdition,
    account: Account,
) -> dict[str, object]:
    assignments = list(
        _current_assignments(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    )
    return {
        "organization_name": edition.organization.name,
        "edition_name": edition.name,
        "can_revoke_assignments": decide(
            principal=account,
            capability_code="authorization.revoke",
            resource=ResourceScope(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            ),
        ).allowed,
        "groups": [
            _group_payload(role) for role in _latest_roles(edition.organization_id)
        ],
        "assignments": [
            _assignment_payload(assignment, edition=edition)
            for assignment in assignments
        ],
    }


def _exact_active_account(email: str, *, field: str) -> Account:
    account = Account.objects.filter(
        email__iexact=email.strip(),
        is_active=True,
    ).first()
    if account is None:
        raise ValidationError(
            {field: "No active account matches that exact email address."}
        )
    return account


def _exact_role(*, organization_id: UUID, code: str) -> RoleBundle:
    role = (
        RoleBundle.objects.filter(
            organization_id=organization_id,
            code=code,
        )
        .exclude(code__in=NON_SHAREABLE_ROLE_CODES)
        .order_by("-version", "id")
        .first()
    )
    if role is None:
        raise ValidationError({"group_code": "Choose an available access group."})
    return role


def _command_validation(error: DjangoValidationError) -> ValidationError:
    if hasattr(error, "message_dict"):
        return ValidationError(error.message_dict)
    return ValidationError({"non_field_errors": error.messages})


class EditionAccessWorkspaceView(APIView):
    @extend_schema(
        operation_id="authorization_retrieve_access_workspace",
        responses=AccessWorkspaceSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        correlation_id = _correlation_id(request)
        _authorize_access(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            audit_read=True,
        )
        edition = _edition(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        payload = _workspace_payload(edition=edition, account=account)
        assignment_count = len(cast(list[object], payload["assignments"]))
        _audit_access_workspace(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="role_assignment",
            target_count=assignment_count,
        )
        return Response(AccessWorkspaceSerializer(payload).data)

    @extend_schema(
        operation_id="authorization_assign_access_group",
        request=AccessAssignmentCreateSerializer,
        responses=AccessWorkspaceSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        correlation_id = _correlation_id(request)
        _authorize_access(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            audit_read=False,
        )
        edition = _edition(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        serializer = AccessAssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = cast(dict[str, Any], serializer.validated_data)
        recipient = _exact_active_account(
            str(values["person_email"]),
            field="person_email",
        )
        approver = _exact_active_account(
            str(values["approver_email"]),
            field="approver_email",
        )
        role = _exact_role(
            organization_id=organization_id,
            code=str(values["group_code"]),
        )
        try:
            assign_role(
                actor=account,
                approver=approver,
                recipient=recipient,
                organization_id=organization_id,
                role_bundle_id=role.id,
                edition_id=edition_id,
                effective_from=timezone.now(),
                expires_at=values.get("expires_at"),
                reason=str(values["reason"]),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="management-console",
            )
        except DjangoPermissionDenied as error:
            raise PermissionDenied(str(error)) from error
        except DjangoValidationError as error:
            raise _command_validation(error) from error
        payload = _workspace_payload(edition=edition, account=account)
        return Response(AccessWorkspaceSerializer(payload).data)


class EditionAccessAssignmentView(APIView):
    @extend_schema(
        operation_id="authorization_replace_access_assignment",
        request=AccessAssignmentReplaceSerializer,
        responses=AccessWorkspaceSerializer,
    )
    def patch(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        assignment_id: UUID,
    ) -> Response:
        account = _account(request)
        correlation_id = _correlation_id(request)
        _authorize_access(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            audit_read=False,
        )
        edition = _edition(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        serializer = AccessAssignmentReplaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = cast(dict[str, Any], serializer.validated_data)
        approver = _exact_active_account(
            str(values["approver_email"]),
            field="approver_email",
        )
        replacement_role = _exact_role(
            organization_id=organization_id,
            code=str(values["group_code"]),
        )
        try:
            with transaction.atomic():
                assignment = (
                    RoleAssignment.objects.select_for_update()
                    .select_related("principal")
                    .filter(
                        pk=assignment_id,
                        organization_id=organization_id,
                        edition_id=edition_id,
                        revoked_at__isnull=True,
                    )
                    .first()
                )
                if assignment is None:
                    raise PermissionDenied("The access assignment is unavailable.")
                reason = str(values["reason"])
                revoke_role_assignment(
                    actor=account,
                    organization_id=organization_id,
                    assignment_id=assignment.id,
                    reason=f"Replaced access: {reason}"[:240],
                    correlation_id=correlation_id,
                    request_id=correlation_id,
                    source_channel="management-console",
                )
                assign_role(
                    actor=account,
                    approver=approver,
                    recipient=assignment.principal,
                    organization_id=organization_id,
                    role_bundle_id=replacement_role.id,
                    edition_id=edition_id,
                    effective_from=timezone.now(),
                    expires_at=values.get("expires_at"),
                    reason=reason,
                    correlation_id=correlation_id,
                    request_id=correlation_id,
                    source_channel="management-console",
                )
        except DjangoPermissionDenied as error:
            raise PermissionDenied(str(error)) from error
        except DjangoValidationError as error:
            raise _command_validation(error) from error
        payload = _workspace_payload(edition=edition, account=account)
        return Response(AccessWorkspaceSerializer(payload).data)

    @extend_schema(
        operation_id="authorization_revoke_access_assignment",
        request=AccessAssignmentRevokeSerializer,
        responses=AccessWorkspaceSerializer,
    )
    def delete(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        assignment_id: UUID,
    ) -> Response:
        account = _account(request)
        correlation_id = _correlation_id(request)
        _authorize_access(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            audit_read=False,
        )
        edition = _edition(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        serializer = AccessAssignmentRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = str(serializer.validated_data["reason"])
        assignment_exists = RoleAssignment.objects.filter(
            pk=assignment_id,
            organization_id=organization_id,
            edition_id=edition_id,
            revoked_at__isnull=True,
        ).exists()
        if not assignment_exists:
            raise PermissionDenied("The access assignment is unavailable.")
        try:
            revoke_role_assignment(
                actor=account,
                organization_id=organization_id,
                assignment_id=assignment_id,
                reason=reason,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="management-console",
            )
        except DjangoPermissionDenied as error:
            raise PermissionDenied(str(error)) from error
        except DjangoValidationError as error:
            raise _command_validation(error) from error
        payload = _workspace_payload(edition=edition, account=account)
        return Response(AccessWorkspaceSerializer(payload).data)
