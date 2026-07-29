"""Verified public identity entry and self-service account safety APIs."""

from uuid import UUID

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.authorization.services import AuthorizationDenied
from maru.identity.models import (
    Account,
    AccountRestriction,
    AccountSession,
    IdentityChallenge,
)
from maru.identity.serializers import (
    AccountBootstrapSerializer,
    AccountRestrictionSerializer,
    AccountSecurityEventSerializer,
    AccountSessionSerializer,
    RecoveryCompleteSerializer,
    RecoveryRequestSerializer,
    RestrictionAppealCreateSerializer,
    RestrictionAppealSerializer,
    SessionSignInSerializer,
    StaffRestrictionAppealDecisionSerializer,
    StaffRestrictionCreateSerializer,
    StaffRestrictionRevokeSerializer,
    StepUpSerializer,
    TokenSerializer,
)
from maru.identity.services import (
    _require_restriction_authority,
    bootstrap_account,
    complete_step_up,
    consume_identity_challenge,
    decide_restriction_appeal,
    enforce_abuse_limit,
    inventory_session,
    issue_account_restriction,
    request_account_recovery,
    request_fingerprint,
    require_recent_step_up,
    revoke_account_restriction,
    revoke_session,
    submit_restriction_appeal,
)


class CsrfTokenView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(operation_id="identity_get_csrf_token", responses=dict)
    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request._request)})


@method_decorator(csrf_protect, name="dispatch")
class PublicSessionView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="identity_create_public_session",
        request=SessionSignInSerializer,
        responses=dict,
    )
    def post(self, request: Request) -> Response:
        serializer = SessionSignInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fingerprint = request_fingerprint(
            request._request,
            contact=serializer.validated_data["email"],
        )
        try:
            enforce_abuse_limit(flow="sign_in", subject_digest=fingerprint)
        except DjangoValidationError as error:
            raise ApiValidationError(
                {"detail": "Sign-in is temporarily unavailable.", "code": error.code}
            ) from error
        account = authenticate(
            request=request._request,
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        if not isinstance(account, Account):
            return Response(
                {"detail": "The email or password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        login(request._request, account)
        inventory_session(account=account, request=request._request)
        return Response(
            {
                "account_id": str(account.id),
                "email_verified": account.has_verified_email,
            },
            status=status.HTTP_201_CREATED,
        )


class PublicAccountBootstrapView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="identity_bootstrap_account",
        request=AccountBootstrapSerializer,
        responses=dict,
    )
    def post(self, request: Request) -> Response:
        serializer = AccountBootstrapSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fingerprint = request_fingerprint(
            request._request,
            contact=serializer.validated_data["email"],
        )
        try:
            _, dispatch = bootstrap_account(
                email=serializer.validated_data["email"],
                display_name=serializer.validated_data["display_name"],
                password=serializer.validated_data["password"],
                fingerprint=fingerprint,
            )
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The account request could not be accepted.",
                    "code": error.code or "account_bootstrap_invalid",
                }
            ) from error
        payload: dict[str, object] = {
            "accepted": True,
            "next": "check_email",
        }
        if dispatch.raw_token is not None:
            payload["test_token"] = dispatch.raw_token
        return Response(payload, status=status.HTTP_202_ACCEPTED)


class PublicVerifyEmailView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="identity_verify_email",
        request=TokenSerializer,
        responses=dict,
    )
    def post(self, request: Request) -> Response:
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            account = consume_identity_challenge(
                raw_token=serializer.validated_data["token"],
                purpose=IdentityChallenge.Purpose.VERIFY_EMAIL,
            )
        except DjangoValidationError as error:
            raise ApiValidationError(
                {"detail": "The verification link is invalid.", "code": error.code}
            ) from error
        return Response(
            {
                "verified": True,
                "account_id": str(account.id),
                "next": "sign_in",
            }
        )


class PublicRecoveryRequestView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="identity_request_recovery",
        request=RecoveryRequestSerializer,
        responses=dict,
    )
    def post(self, request: Request) -> Response:
        serializer = RecoveryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fingerprint = request_fingerprint(
            request._request,
            contact=serializer.validated_data["email"],
        )
        try:
            dispatch = request_account_recovery(
                email=serializer.validated_data["email"],
                fingerprint=fingerprint,
            )
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "Recovery is temporarily unavailable.",
                    "code": error.code,
                }
            ) from error
        payload: dict[str, object] = {
            "accepted": True,
            "next": "check_email",
        }
        if dispatch.raw_token is not None:
            payload["test_token"] = dispatch.raw_token
        return Response(payload, status=status.HTTP_202_ACCEPTED)


class PublicRecoveryCompleteView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="identity_complete_recovery",
        request=RecoveryCompleteSerializer,
        responses=dict,
    )
    def post(self, request: Request) -> Response:
        serializer = RecoveryCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            consume_identity_challenge(
                raw_token=serializer.validated_data["token"],
                purpose=IdentityChallenge.Purpose.RECOVER_ACCOUNT,
                new_password=serializer.validated_data["new_password"],
            )
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "Account recovery could not be completed.",
                    "code": error.code,
                }
            ) from error
        return Response({"recovered": True, "next": "sign_in"})


class MySecurityHistoryView(APIView):
    @extend_schema(
        operation_id="identity_list_my_security_history",
        responses=AccountSecurityEventSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        if not isinstance(request.user, Account):
            raise TypeError("Authenticated principal is not a platform account")
        events = request.user.security_events.order_by("-occurred_at", "-id")[:100]
        return Response(AccountSecurityEventSerializer(events, many=True).data)


class MySessionListView(APIView):
    @extend_schema(
        operation_id="identity_list_my_sessions",
        responses=AccountSessionSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        if not isinstance(request.user, Account):
            raise TypeError("Authenticated principal is not a platform account")
        current = inventory_session(account=request.user, request=request._request)
        items = request.user.account_sessions.order_by("-last_seen_at", "-id")[:100]
        data = AccountSessionSerializer(items, many=True).data
        current_id = str(current.id) if current else None
        for row in data:
            row["current"] = str(row["id"]) == current_id
        return Response(data)


class MySessionRevokeView(APIView):
    @extend_schema(
        operation_id="identity_revoke_my_session",
        request=None,
        responses=dict,
    )
    def post(self, request: Request, session_id: UUID) -> Response:
        if not isinstance(request.user, Account):
            raise TypeError("Authenticated principal is not a platform account")
        try:
            item = revoke_session(account=request.user, session_id=session_id)
        except AccountSession.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({"id": str(item.id), "revoked": True})


class MyStepUpView(APIView):
    @extend_schema(
        operation_id="identity_complete_step_up",
        request=StepUpSerializer,
        responses=dict,
    )
    def post(self, request: Request) -> Response:
        if not isinstance(request.user, Account):
            raise TypeError("Authenticated principal is not a platform account")
        serializer = StepUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = complete_step_up(
                account=request.user,
                request=request._request,
                password=serializer.validated_data["password"],
            )
        except DjangoValidationError as error:
            raise ApiValidationError(
                {"detail": "The extra sign-in check failed.", "code": error.code}
            ) from error
        return Response(
            {
                "session_id": str(item.id),
                "step_up_verified_at": item.step_up_verified_at,
            }
        )


class MyRestrictionListView(APIView):
    @extend_schema(
        operation_id="identity_list_my_restrictions",
        responses=AccountRestrictionSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        if not isinstance(request.user, Account):
            raise TypeError("Authenticated principal is not a platform account")
        items = (
            request.user.restrictions.select_related("organization", "edition")
            .prefetch_related("appeals")
            .order_by("-effective_at", "-id")[:100]
        )
        return Response(AccountRestrictionSerializer(items, many=True).data)


class MyRestrictionAppealView(APIView):
    @extend_schema(
        operation_id="identity_appeal_my_restriction",
        request=RestrictionAppealCreateSerializer,
        responses=RestrictionAppealSerializer,
    )
    def post(self, request: Request, restriction_id: UUID) -> Response:
        if not isinstance(request.user, Account):
            raise TypeError("Authenticated principal is not a platform account")
        serializer = RestrictionAppealCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = submit_restriction_appeal(
                account=request.user,
                restriction_id=restriction_id,
                statement=serializer.validated_data["statement"],
            )
        except ObjectDoesNotExist as error:
            raise NotFound("The restriction is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {"detail": "The appeal could not be submitted.", "code": error.code}
            ) from error
        return Response(
            RestrictionAppealSerializer(item).data,
            status=status.HTTP_201_CREATED,
        )


class StaffRestrictionListCreateView(APIView):
    @extend_schema(
        operation_id="identity_list_scoped_restrictions",
        responses=AccountRestrictionSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        if not isinstance(request.user, Account):
            raise TypeError("Authenticated principal is not a platform account")
        try:
            _require_restriction_authority(
                actor=request.user,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Restriction management is unavailable.",
                code=error.reason_code,
            ) from error
        items = AccountRestriction.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        ).prefetch_related("appeals")[:100]
        return Response(AccountRestrictionSerializer(items, many=True).data)

    @extend_schema(
        operation_id="identity_issue_scoped_restriction",
        request=StaffRestrictionCreateSerializer,
        responses={201: AccountRestrictionSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        if not isinstance(request.user, Account):
            raise TypeError("Authenticated principal is not a platform account")
        serializer = StaffRestrictionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            if settings.REQUIRE_PRIVILEGED_STEP_UP:
                require_recent_step_up(account=request.user, request=request._request)
            target = Account.objects.get(id=values["account_id"])
            item = issue_account_restriction(
                actor=request.user,
                account=target,
                organization_id=organization_id,
                edition_id=edition_id,
                kind=values["kind"],
                reason_code=values["reason_code"],
                attendee_message=values["attendee_message"],
                internal_reference=values.get("internal_reference", ""),
                effective_at=values["effective_at"],
                expires_at=values.get("expires_at"),
                notify_account=values["notify_account"],
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Restriction management is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The target account is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {"detail": "The restriction could not be issued.", "code": error.code}
            ) from error
        return Response(AccountRestrictionSerializer(item).data, status=201)


class StaffRestrictionRevokeView(APIView):
    @extend_schema(
        operation_id="identity_revoke_scoped_restriction",
        request=StaffRestrictionRevokeSerializer,
        responses=AccountRestrictionSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        restriction_id: UUID,
    ) -> Response:
        if not isinstance(request.user, Account):
            raise TypeError("Authenticated principal is not a platform account")
        serializer = StaffRestrictionRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            if settings.REQUIRE_PRIVILEGED_STEP_UP:
                require_recent_step_up(account=request.user, request=request._request)
            item = revoke_account_restriction(
                actor=request.user,
                organization_id=organization_id,
                edition_id=edition_id,
                restriction_id=restriction_id,
                reason=serializer.validated_data["reason"],
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Restriction management is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The restriction is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {"detail": "The restriction could not be revoked.", "code": error.code}
            ) from error
        return Response(AccountRestrictionSerializer(item).data)


class StaffRestrictionAppealDecisionView(APIView):
    @extend_schema(
        operation_id="identity_decide_restriction_appeal",
        request=StaffRestrictionAppealDecisionSerializer,
        responses=RestrictionAppealSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        appeal_id: UUID,
    ) -> Response:
        if not isinstance(request.user, Account):
            raise TypeError("Authenticated principal is not a platform account")
        serializer = StaffRestrictionAppealDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            if settings.REQUIRE_PRIVILEGED_STEP_UP:
                require_recent_step_up(account=request.user, request=request._request)
            item = decide_restriction_appeal(
                actor=request.user,
                organization_id=organization_id,
                edition_id=edition_id,
                appeal_id=appeal_id,
                decision=serializer.validated_data["decision"],
                summary=serializer.validated_data["summary"],
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Restriction appeal review is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The appeal is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {"detail": "The appeal could not be decided.", "code": error.code}
            ) from error
        return Response(RestrictionAppealSerializer(item).data)
