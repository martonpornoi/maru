"""API-first volunteer opportunity and self-service onboarding clients."""

from typing import Never, cast
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Exists, OuterRef, Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.authorization.policy import ResourceScope, decide
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.bootstrap import bootstrap_organization_workforce
from maru.workforce.models import (
    Department,
    OnboardingDocumentRequest,
    Position,
    PositionAssignment,
    VolunteerOpportunity,
)
from maru.workforce.serializers import (
    ConventionBootstrapRequestSerializer,
    ConventionBootstrapResultSerializer,
    ConventionBootstrapWorkspaceSerializer,
    OnboardingDocumentRequestSerializer,
    OnboardingDocumentUploadSerializer,
    VolunteerApplicationSerializer,
    VolunteerApplicationSubmitSerializer,
    VolunteerOpportunitySerializer,
    WorkforceStructureSerializer,
)
from maru.workforce.services import (
    submit_volunteer_application,
    upload_onboarding_document,
)


def _account(request: Request) -> Account:
    if not isinstance(request.user, Account):
        raise PermissionDenied("Sign in to use workforce self-service.")
    return request.user


def _bootstrap_audit(
    *,
    account: Account,
    correlation_id: UUID,
    operation: str,
    outcome: str,
    reason_code: str,
    organization_id: UUID | None = None,
    edition_id: UUID | None = None,
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
            capability_code="authorization.manage_roles",
            operation=operation,
            target_type="workforce.convention_bootstrap",
            target_id=organization_id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="management-console",
            obligations=("current_password", "exact_confirmation", "audit"),
            elevated=True,
            safe_metadata=safe_metadata,
            retention_class="security-extended",
        )
    )


def _bootstrap_controller(request: Request) -> tuple[Account, UUID]:
    account = _account(request)
    correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
    if not account.is_active or not account.is_superuser:
        _bootstrap_audit(
            account=account,
            correlation_id=correlation_id,
            operation="workforce.convention_bootstrap.view",
            outcome=AuditEvent.Outcome.DENY,
            reason_code="bootstrap_superuser_required",
        )
        raise PermissionDenied(
            "Initial convention leadership is available only to an active "
            "bootstrap administrator.",
            code="bootstrap_superuser_required",
        )
    return account, correlation_id


def _bootstrap_workspace_payload(controller: Account) -> dict[str, object]:
    authority_roles = RoleBundle.objects.filter(organization_id=OuterRef("pk"))
    authority_assignments = RoleAssignment.objects.filter(
        organization_id=OuterRef("pk")
    )
    direct_grants = CapabilityGrant.objects.filter(organization_id=OuterRef("pk"))
    organization_rows = list(
        Organization.objects.filter(lifecycle=Organization.Lifecycle.ACTIVE)
        .annotate(
            has_roles=Exists(authority_roles),
            has_assignments=Exists(authority_assignments),
            has_grants=Exists(direct_grants),
        )
        .values(
            "id",
            "slug",
            "name",
            "has_roles",
            "has_assignments",
            "has_grants",
        )
        .order_by("name", "id")
    )
    organizations = [
        {
            "id": row["id"],
            "slug": row["slug"],
            "name": row["name"],
            "status": (
                "established"
                if row["has_roles"] or row["has_assignments"] or row["has_grants"]
                else "eligible"
            ),
        }
        for row in organization_rows
    ]
    editions = list(
        EventEdition.objects.filter(
            organization__lifecycle=Organization.Lifecycle.ACTIVE,
        )
        .exclude(
            lifecycle__in=(
                EventEdition.Lifecycle.ARCHIVED,
                EventEdition.Lifecycle.CANCELLED,
            )
        )
        .values(
            "id",
            "organization_id",
            "slug",
            "name",
            "lifecycle",
            "starts_on",
            "ends_on",
        )
        .order_by("organization__name", "-starts_on", "name", "id")
    )
    chairs = list(
        Account.objects.filter(is_active=True)
        .exclude(id=controller.id)
        .values("email", "display_name")
        .order_by("display_name", "email")[:250]
    )
    return {
        "controller_email": controller.email,
        "organizations": organizations,
        "editions": editions,
        "chairs": chairs,
    }


class ConventionBootstrapWorkspaceView(APIView):
    @extend_schema(
        operation_id="workforce_retrieve_convention_bootstrap_workspace",
        responses=ConventionBootstrapWorkspaceSerializer,
    )
    def get(self, request: Request) -> Response:
        controller, correlation_id = _bootstrap_controller(request)
        payload = _bootstrap_workspace_payload(controller)
        target_count = len(cast(list[object], payload["chairs"]))
        _bootstrap_audit(
            account=controller,
            correlation_id=correlation_id,
            operation="workforce.convention_bootstrap.view",
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="bootstrap_workspace_available",
            target_count=target_count,
        )
        return Response(ConventionBootstrapWorkspaceSerializer(payload).data)

    @extend_schema(
        operation_id="workforce_create_convention_bootstrap",
        request=ConventionBootstrapRequestSerializer,
        responses={201: ConventionBootstrapResultSerializer},
    )
    def post(self, request: Request) -> Response:
        controller, correlation_id = _bootstrap_controller(request)
        serializer = ConventionBootstrapRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        organization_id = cast(UUID, values["organization_id"])
        edition_id = cast(UUID, values["edition_id"])
        organization = Organization.objects.filter(
            id=organization_id,
            lifecycle=Organization.Lifecycle.ACTIVE,
        ).first()
        edition = (
            EventEdition.objects.filter(
                id=edition_id,
                organization_id=organization_id,
            )
            .exclude(
                lifecycle__in=(
                    EventEdition.Lifecycle.ARCHIVED,
                    EventEdition.Lifecycle.CANCELLED,
                )
            )
            .first()
        )

        def reject(detail: str, code: str) -> Never:
            _bootstrap_audit(
                account=controller,
                correlation_id=correlation_id,
                operation="workforce.convention_bootstrap",
                outcome=AuditEvent.Outcome.DENY,
                reason_code=code,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            raise ApiValidationError({"detail": detail, "code": code})

        if organization is None or edition is None:
            reject(
                "Choose a matching active organization and non-closed edition.",
                "bootstrap_scope_invalid",
            )
        if (
            cast(str, values["confirm_organization"]).casefold()
            != organization.slug.casefold()
        ):
            reject(
                f"Type {organization.slug} exactly to confirm.",
                "bootstrap_confirmation_mismatch",
            )
        if not controller.check_password(cast(str, values["controller_password"])):
            reject(
                "The administrator password is incorrect.",
                "bootstrap_password_invalid",
            )
        chair = Account.objects.filter(
            email__iexact=cast(str, values["chair_email"]).strip(),
            is_active=True,
        ).first()
        if chair is None or chair.id == controller.id:
            reject(
                "Choose a distinct active Convention Chair account.",
                "bootstrap_chair_invalid",
            )
        try:
            created = bootstrap_organization_workforce(
                organization=organization,
                edition=edition,
                controller=controller,
                chair=chair,
                reason=cast(str, values["reason"]),
                correlation_id=correlation_id,
                source_channel="management-console",
            )
        except DjangoValidationError as error:
            reject(error.messages[0], "bootstrap_unavailable")
        payload = {
            "organization": {
                "id": organization.id,
                "slug": organization.slug,
                "name": organization.name,
                "status": "established",
            },
            "edition": {
                "id": edition.id,
                "organization_id": organization.id,
                "slug": edition.slug,
                "name": edition.name,
                "lifecycle": edition.lifecycle,
                "starts_on": edition.starts_on,
                "ends_on": edition.ends_on,
            },
            "chair": {
                "email": chair.email,
                "display_name": chair.display_name,
            },
            "created": created,
        }
        return Response(
            ConventionBootstrapResultSerializer(payload).data,
            status=status.HTTP_201_CREATED,
        )


class WorkforceStructureView(APIView):
    """Return the current, human-readable edition organization hierarchy."""

    @extend_schema(
        operation_id="workforce_retrieve_structure",
        responses=WorkforceStructureSerializer,
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        edition = get_object_or_404(
            EventEdition.objects.select_related("organization"),
            id=edition_id,
            organization_id=organization_id,
        )
        decision = decide(
            principal=account,
            capability_code="workforce.view_structure",
            resource=ResourceScope(
                organization_id=organization_id,
                edition_id=edition_id,
            ),
        )
        if not decision.allowed:
            raise PermissionDenied(
                "This account cannot view the organization structure.",
                code=decision.reason_code,
            )

        active_assignments = (
            PositionAssignment.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                status=PositionAssignment.Status.ACTIVE,
            )
            .select_related("account", "position", "position__department")
            .order_by(
                "account__login_handle",
                "account__display_name",
                "account_id",
                "id",
            )
        )
        positions = (
            Position.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .exclude(status=Position.Status.CLOSED)
            .prefetch_related(
                Prefetch(
                    "assignments",
                    queryset=active_assignments,
                    to_attr="active_holders",
                )
            )
            .order_by("title", "id")
        )
        departments = list(
            Department.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .prefetch_related(
                Prefetch("positions", queryset=positions, to_attr="current_positions")
            )
            .order_by("position", "name", "id")
        )

        roles_by_account: dict[UUID, list[dict[str, str]]] = {}
        for department in departments:
            for position in department.current_positions:
                for assignment in position.active_holders:
                    roles_by_account.setdefault(assignment.account_id, []).append(
                        {
                            "department_name": department.name,
                            "position_title": position.title,
                        }
                    )

        department_payload: list[dict[str, object]] = []
        for department in departments:
            position_payload: list[dict[str, object]] = []
            for position in department.current_positions:
                holder_payload: list[dict[str, object]] = []
                for assignment in position.active_holders:
                    account_roles = roles_by_account.get(assignment.account_id, [])
                    holder_payload.append(
                        {
                            "assignment_id": assignment.id,
                            "display_name": (
                                assignment.account.display_name
                                or assignment.account.login_handle
                                or "Maru account"
                            ),
                            "login_handle": assignment.account.login_handle,
                            "other_roles": [
                                role
                                for role in account_roles
                                if not (
                                    role["department_name"] == department.name
                                    and role["position_title"] == position.title
                                )
                            ],
                        }
                    )
                position_payload.append(
                    {
                        "id": position.id,
                        "reports_to_id": position.reports_to_id,
                        "code": position.code,
                        "title": position.title,
                        "description": position.description,
                        "headcount": position.headcount,
                        "status": position.status,
                        "holders": holder_payload,
                    }
                )
            department_payload.append(
                {
                    "id": department.id,
                    "parent_id": department.parent_id,
                    "code": department.code,
                    "name": department.name,
                    "description": department.description,
                    "positions": position_payload,
                }
            )

        payload: dict[str, object] = {
            "organization_name": edition.organization.name,
            "edition_name": edition.name,
            "departments": department_payload,
        }
        return Response(WorkforceStructureSerializer(payload).data)


def _opportunity_payload(opportunity: VolunteerOpportunity) -> dict[str, object]:
    position = opportunity.position
    return {
        "id": opportunity.id,
        "position_code": position.code,
        "position_title": position.title,
        "department_name": position.department.name,
        "reports_to_title": (
            position.reports_to.title if position.reports_to is not None else None
        ),
        "headline": opportunity.headline,
        "description": opportunity.description,
        "headcount": position.headcount,
        "active_assignment_count": opportunity.active_assignment_count,
        "is_filled": opportunity.is_filled,
        "accepts_applications": opportunity.accepts_applications,
        "applications_open_at": opportunity.applications_open_at,
        "applications_close_at": opportunity.applications_close_at,
    }


def _document_payload(item: OnboardingDocumentRequest) -> dict[str, object]:
    return {
        "id": item.id,
        "document_type_code": item.document_type.code,
        "document_type_name": item.document_type.name,
        "document_type_version": item.document_type.version,
        "status": item.status,
        "instructions": item.instructions,
        "due_at": item.due_at,
        "requested_at": item.requested_at,
        "submitted_at": item.submitted_at,
        "reviewed_at": item.reviewed_at,
        "review_reason": item.review_reason,
        "original_filename": item.original_filename,
        "upload_available": item.status
        in {
            OnboardingDocumentRequest.Status.REQUESTED,
            OnboardingDocumentRequest.Status.REJECTED,
        },
    }


class PublicVolunteerOpportunityListView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="workforce_list_public_volunteer_opportunities",
        responses=VolunteerOpportunitySerializer(many=True),
    )
    def get(self, request: Request, edition_id: UUID) -> Response:
        del request
        edition = get_object_or_404(
            EventEdition.objects.exclude(lifecycle__in=("archived", "cancelled")),
            id=edition_id,
        )
        candidates = (
            VolunteerOpportunity.objects.filter(
                position__edition=edition,
                status=VolunteerOpportunity.Status.PUBLISHED,
            )
            .select_related(
                "position",
                "position__department",
                "position__reports_to",
            )
            .order_by("position__department__position", "position__title", "id")
        )
        payload = [
            _opportunity_payload(item)
            for item in candidates
            if not item.is_filled or item.visible_when_filled
        ]
        return Response(
            VolunteerOpportunitySerializer(
                instance=payload,  # type: ignore[arg-type]
                many=True,
            ).data
        )


class MyVolunteerApplicationCreateView(APIView):
    @extend_schema(
        operation_id="workforce_submit_my_volunteer_application",
        request=VolunteerApplicationSubmitSerializer,
        responses={201: VolunteerApplicationSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        opportunity_id: UUID,
    ) -> Response:
        account = _account(request)
        serializer = VolunteerApplicationSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not VolunteerOpportunity.objects.filter(
            id=opportunity_id,
            position__organization_id=organization_id,
            position__edition_id=edition_id,
        ).exists():
            raise NotFound("The volunteer opportunity is unavailable.")
        try:
            application = submit_volunteer_application(
                actor=account,
                opportunity_id=opportunity_id,
                motivation=cast(str, serializer.validated_data["motivation"]),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except (ObjectDoesNotExist, DjangoValidationError) as error:
            raise ApiValidationError(
                {
                    "detail": "The volunteer application could not be submitted.",
                    "code": "volunteer_application_invalid",
                }
            ) from error
        payload = {
            "id": application.id,
            "opportunity_id": application.opportunity_id,
            "status": application.status,
            "submitted_at": application.submitted_at,
        }
        return Response(
            VolunteerApplicationSerializer(
                instance=payload,
            ).data,
            status=201,
        )


class MyOnboardingDocumentListView(APIView):
    @extend_schema(
        operation_id="workforce_list_my_onboarding_documents",
        responses=OnboardingDocumentRequestSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = _account(request)
        decision = decide(
            principal=account,
            capability_code="workforce.view_self",
            resource=ResourceScope(
                organization_id=organization_id,
                edition_id=edition_id,
                owner_account_id=account.id,
            ),
        )
        if not decision.allowed:
            raise NotFound("Onboarding documents are unavailable.")
        items = (
            OnboardingDocumentRequest.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                account=account,
            )
            .select_related("document_type")
            .order_by("status", "due_at", "id")
        )
        payload = [_document_payload(item) for item in items]
        return Response(
            OnboardingDocumentRequestSerializer(
                instance=payload,  # type: ignore[arg-type]
                many=True,
            ).data
        )


class MyOnboardingDocumentUploadView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        operation_id="workforce_upload_my_onboarding_document",
        request=OnboardingDocumentUploadSerializer,
        responses=OnboardingDocumentRequestSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        document_request_id: UUID,
    ) -> Response:
        account = _account(request)
        serializer = OnboardingDocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not OnboardingDocumentRequest.objects.filter(
            id=document_request_id,
            organization_id=organization_id,
            edition_id=edition_id,
            account=account,
        ).exists():
            raise NotFound("The onboarding document request is unavailable.")
        try:
            item = upload_onboarding_document(
                actor=account,
                request_id=document_request_id,
                upload=cast(UploadedFile, serializer.validated_data["document"]),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except (ObjectDoesNotExist, DjangoValidationError) as error:
            raise ApiValidationError(
                {
                    "detail": "The onboarding document could not be uploaded.",
                    "code": "onboarding_document_invalid",
                }
            ) from error
        return Response(
            OnboardingDocumentRequestSerializer(
                instance=_document_payload(item),
            ).data
        )
