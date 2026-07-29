"""API-first volunteer opportunity and self-service onboarding clients."""

from typing import cast
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import UploadedFile
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.authorization.policy import ResourceScope, decide
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.workforce.models import (
    OnboardingDocumentRequest,
    VolunteerOpportunity,
)
from maru.workforce.serializers import (
    OnboardingDocumentRequestSerializer,
    OnboardingDocumentUploadSerializer,
    VolunteerApplicationSerializer,
    VolunteerApplicationSubmitSerializer,
    VolunteerOpportunitySerializer,
)
from maru.workforce.services import (
    submit_volunteer_application,
    upload_onboarding_document,
)


def _account(request: Request) -> Account:
    if not isinstance(request.user, Account):
        raise PermissionDenied("Sign in to use workforce self-service.")
    return request.user


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
