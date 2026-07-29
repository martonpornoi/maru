"""Self-service privacy intake and scoped historical correction review."""

from uuid import UUID

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
)
from rest_framework.exceptions import (
    ValidationError as ApiValidationError,
)
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account
from maru.identity.services import require_recent_step_up
from maru.privacyops.models import PostEditionCorrection, SubjectRightsRequest
from maru.privacyops.serializers import (
    DisposalReceiptSerializer,
    PostEditionCorrectionCreateSerializer,
    PostEditionCorrectionDecisionSerializer,
    PostEditionCorrectionSerializer,
    RegistrationProfileMinimizeSerializer,
    StaffSubjectRightsRequestSerializer,
    SubjectRightsRequestCreateSerializer,
    SubjectRightsRequestSerializer,
    SubjectRightsRequestTransitionSerializer,
)
from maru.privacyops.services import (
    build_subject_export,
    create_subject_rights_request,
    decide_profile_correction,
    minimize_registration_profile,
    propose_profile_correction,
    transition_subject_rights_request,
)


def _account(request: Request) -> Account:
    if not isinstance(request.user, Account):
        raise TypeError("Authenticated principal is not a platform account")
    return request.user


class MySubjectRightsRequestListCreateView(APIView):
    @extend_schema(
        operation_id="privacy_list_my_requests",
        responses=SubjectRightsRequestSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        items = SubjectRightsRequest.objects.filter(account=_account(request)).order_by(
            "-requested_at", "-id"
        )
        return Response(SubjectRightsRequestSerializer(items, many=True).data)

    @extend_schema(
        operation_id="privacy_create_my_request",
        request=SubjectRightsRequestCreateSerializer,
        responses={201: SubjectRightsRequestSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = SubjectRightsRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            item = create_subject_rights_request(
                account=_account(request),
                organization_id=values.get("organization_id"),
                kind=values["kind"],
                summary=values["summary"],
            )
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The privacy request could not be submitted.",
                    "code": error.code or "privacy_request_invalid",
                }
            ) from error
        return Response(SubjectRightsRequestSerializer(item).data, status=201)


class MySubjectExportView(APIView):
    @extend_schema(operation_id="privacy_generate_my_export", responses=dict)
    def get(self, request: Request) -> Response:
        raw_organization = request.query_params.get("organization_id")
        try:
            organization_id = UUID(raw_organization) if raw_organization else None
        except ValueError as error:
            raise ApiValidationError(
                {
                    "detail": "The organization identifier is invalid.",
                    "code": "organization_id_invalid",
                }
            ) from error
        return Response(
            build_subject_export(
                account=_account(request),
                organization_id=organization_id,
            )
        )


class StaffSubjectRightsRequestListView(APIView):
    @extend_schema(
        operation_id="privacy_list_staff_requests",
        responses=StaffSubjectRightsRequestSerializer(many=True),
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        account = _account(request)
        from maru.authorization.policy import ResourceScope, decide  # noqa: PLC0415

        decision = decide(
            principal=account,
            capability_code="privacy.manage_requests",
            resource=ResourceScope(organization_id=organization_id),
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Privacy requests are unavailable.",
                code=decision.reason_code,
            )
        items = (
            SubjectRightsRequest.objects.filter(organization_id=organization_id)
            .select_related("account")
            .order_by("status", "requested_at", "id")[:250]
        )
        return Response(StaffSubjectRightsRequestSerializer(items, many=True).data)


class StaffSubjectRightsRequestTransitionView(APIView):
    @extend_schema(
        operation_id="privacy_transition_staff_request",
        request=SubjectRightsRequestTransitionSerializer,
        responses=StaffSubjectRightsRequestSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        privacy_request_id: UUID,
    ) -> Response:
        serializer = SubjectRightsRequestTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        account = _account(request)
        try:
            if settings.REQUIRE_PRIVILEGED_STEP_UP:
                require_recent_step_up(account=account, request=request._request)
            item = transition_subject_rights_request(
                actor=account,
                organization_id=organization_id,
                request_id=privacy_request_id,
                action=values["action"],
                outcome_summary=values.get("outcome_summary", ""),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Privacy request management is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The privacy request is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The privacy request could not be updated.",
                    "code": error.code or "privacy_request_invalid",
                }
            ) from error
        return Response(StaffSubjectRightsRequestSerializer(item).data)


class MyPostEditionCorrectionListCreateView(APIView):
    @extend_schema(
        operation_id="privacy_list_my_corrections",
        responses=PostEditionCorrectionSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        items = PostEditionCorrection.objects.filter(
            account_id=_account(request).id
        ).order_by("-requested_at", "-id")
        return Response(PostEditionCorrectionSerializer(items, many=True).data)

    @extend_schema(
        operation_id="privacy_propose_my_correction",
        request=PostEditionCorrectionCreateSerializer,
        responses={201: PostEditionCorrectionSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = PostEditionCorrectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            item = propose_profile_correction(
                account=_account(request),
                profile_id=values["profile_id"],
                changed_fields=values["changed_fields"],
                reason=values["reason"],
            )
        except ObjectDoesNotExist as error:
            raise NotFound("The profile is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The correction could not be proposed.",
                    "code": error.code or "post_edition_correction_invalid",
                }
            ) from error
        return Response(PostEditionCorrectionSerializer(item).data, status=201)


class StaffPostEditionCorrectionDecisionView(APIView):
    @extend_schema(
        operation_id="privacy_decide_post_edition_correction",
        request=PostEditionCorrectionDecisionSerializer,
        responses=PostEditionCorrectionSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        correction_id: UUID,
    ) -> Response:
        serializer = PostEditionCorrectionDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            item = decide_profile_correction(
                actor=_account(request),
                organization_id=organization_id,
                edition_id=edition_id,
                correction_id=correction_id,
                approve=values["approve"],
                reason=values["reason"],
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Historical correction review is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The correction is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The correction could not be decided.",
                    "code": error.code or "post_edition_correction_invalid",
                }
            ) from error
        return Response(PostEditionCorrectionSerializer(item).data)


class StaffRegistrationProfileMinimizeView(APIView):
    @extend_schema(
        operation_id="privacy_minimize_registration_profile",
        request=RegistrationProfileMinimizeSerializer,
        responses={201: DisposalReceiptSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        serializer = RegistrationProfileMinimizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        account = _account(request)
        try:
            if settings.REQUIRE_PRIVILEGED_STEP_UP:
                require_recent_step_up(account=account, request=request._request)
            receipt = minimize_registration_profile(
                actor=account,
                organization_id=organization_id,
                edition_id=edition_id,
                profile_id=values["profile_id"],
                policy_id=values["policy_id"],
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Registration retention is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The retention target is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The profile could not be minimized.",
                    "code": error.code or "retention_operation_invalid",
                }
            ) from error
        return Response(DisposalReceiptSerializer(receipt).data, status=201)
