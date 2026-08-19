"""Strict versioned API adapters for Page 10 account invitations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Never, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.core.api_input import reject_unknown_fields
from maru.core.problems import DependencyUnavailable
from maru.identity.invitation_audit import append_platform_account_read_audit
from maru.identity.invitation_commands import (
    AccountInvitationCommandResult,
    InvitationAuthorizationDeniedError,
    InvitationChallengeInvalidError,
    InvitationCommandError,
    InvitationDependencyUnavailableError,
    InvitationIdentityConflictError,
    InvitationRetryConflictError,
    InvitationStateConflictError,
    InvitationUnavailableError,
    InvitationVersionConflictError,
    accept_platform_account_invitation,
    create_platform_account_invitation,
    reissue_platform_account_invitation,
    revoke_platform_account_invitation,
)
from maru.identity.invitation_queries import (
    AccountInventoryPage,
    AccountInvitationDetail,
    PlatformAccountInventoryCursorStaleError,
    PlatformAccountInventoryDeniedError,
    PlatformAccountInventoryInputError,
    PlatformAccountInventoryLimitExceededError,
    PlatformAccountInventoryUnavailableError,
    PlatformAccountInvitationNotFoundError,
    load_platform_account_inventory,
    load_platform_account_invitation_detail,
)
from maru.identity.invitation_serializers import (
    PlatformAccountInventoryQuerySerializer,
    PlatformAccountInventorySerializer,
    PlatformAccountInvitationActionSerializer,
    PlatformAccountInvitationCreateSerializer,
    PlatformAccountInvitationDetailSerializer,
    PlatformAccountInvitationMutationSerializer,
    PlatformAccountInvitationProblemSerializer,
    PublicAccountInvitationAcceptanceResultSerializer,
    PublicAccountInvitationAcceptanceSerializer,
)
from maru.identity.models import Account
from maru.identity.services import request_fingerprint, require_recent_step_up

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rest_framework.request import Request

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"
IDEMPOTENCY_HEADER_NAME = "Idempotency-Key"
MAX_IDEMPOTENCY_HEADER_LENGTH = 64
CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_PROTECTED_UNAVAILABLE_DETAIL = "Platform account invitations are unavailable."
_PUBLIC_INVALID_DETAIL = "The invitation could not be accepted."
_SAFE_PASSWORD_VALIDATION_ERRORS = {
    "password_too_short": (
        "invitation_password_too_short",
        "Choose a longer password.",
    ),
    "password_too_common": (
        "invitation_password_too_common",
        "Choose a less common password.",
    ),
    "password_entirely_numeric": (
        "invitation_password_entirely_numeric",
        "Use a password that is not entirely numeric.",
    ),
    "password_too_similar": (
        "invitation_password_too_similar",
        "Choose a password that is less similar to your account details.",
    ),
}
_GENERIC_PASSWORD_VALIDATION = (
    "invitation_password_invalid",
    "Choose a password that meets the account password policy.",
)


def _problem_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(
        response=PlatformAccountInvitationProblemSerializer,
        description=description,
    )


_IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name=IDEMPOTENCY_HEADER_NAME,
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    pattern=CANONICAL_UUID_PATTERN,
    description=(
        "A canonical lower-case hyphenated UUID. Reuse with the same actor, "
        "operation, target, and normalized input recovers the first result; "
        "changed reuse conflicts. The key is never accepted in JSON."
    ),
)


class InvitationConflict(APIException):
    """Name-free RFC 9457 boundary for invitation command conflicts."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The invitation request conflicts with current state."
    default_code = "account_invitation_conflict"

    def __init__(
        self,
        *,
        code: str,
        errors: Mapping[str, list[str]],
    ) -> None:
        """Initialize the InvitationConflict instance.

        Parameters
        ----------
        code : str
            The stable domain code to resolve or validate.
        errors : Mapping[str, list[str]]
            The errors evaluated while invitation conflict.
        """
        super().__init__(
            detail=cast(
                "Any",
                {
                    "detail": self.default_detail,
                    "code": code,
                    "errors": dict(errors),
                },
            ),
            code=code,
        )


class InvitationAcceptanceRateLimited(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "The invitation cannot be checked right now. Try again later."
    default_code = "identity_rate_limited"


def _request_id(request: Request) -> UUID:
    candidate = getattr(request, "correlation_id", None)
    if isinstance(candidate, str):
        try:
            return UUID(candidate)
        except ValueError:
            pass
    return uuid4()


def _safe_dependency_failure(
    *,
    request: Request,
    operation: str,
    error: Exception,
) -> Never:
    # Do not attach the exception text or request representation: database and
    # validation errors can contain C2/C4 input. The correlation identifier and
    # safe class are enough to join restricted diagnostics.
    logger.error(
        "Platform account invitation API dependency failed",
        extra={
            "correlation_id": str(_request_id(request)),
            "operation": operation,
            "failure_class": type(error).__name__,
        },
    )
    raise DependencyUnavailable from error


def _active_platform_administrator(
    request: Request,
    *,
    require_step_up: bool,
) -> Account:
    """Resolve fresh platform authority before reading headers or JSON.

    Parameters
    ----------
    request : Request
        The incoming HTTP request and authenticated principal context.
    require_step_up : bool
        Whether to require step up.

    Returns
    -------
    Account
        The resolved Account for active platform administrator.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    principal = request.user
    if not isinstance(principal, Account) or not principal.is_authenticated:
        raise PermissionDenied(
            _PROTECTED_UNAVAILABLE_DETAIL,
            code=InvitationAuthorizationDeniedError.reason_code,
        )
    try:
        actor = (
            Account.objects.filter(
                id=principal.id,
                is_active=True,
                is_staff=True,
                is_superuser=True,
                account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
            )
            .order_by("id")
            .first()
        )
    except (DatabaseError, RuntimeError) as error:
        _safe_dependency_failure(
            request=request,
            operation="authorize_platform_account_invitation",
            error=error,
        )
    if actor is None:
        raise PermissionDenied(
            _PROTECTED_UNAVAILABLE_DETAIL,
            code=InvitationAuthorizationDeniedError.reason_code,
        )
    if require_step_up and settings.REQUIRE_PRIVILEGED_STEP_UP:
        try:
            require_recent_step_up(account=actor, request=request._request)
        except DjangoValidationError as error:
            raise PermissionDenied(
                _PROTECTED_UNAVAILABLE_DETAIL,
                code="step_up_required",
            ) from error
    return actor


def _raise_idempotency_error(*, detail: str, code: str) -> Never:
    raise ApiValidationError(
        cast(
            "Any",
            {
                "detail": detail,
                "code": code,
                "errors": {IDEMPOTENCY_HEADER_NAME: [detail]},
            },
        ),
        code=code,
    )


def _idempotency_key(request: Request) -> UUID:
    raw_value = request.headers.get(IDEMPOTENCY_HEADER_NAME)
    if raw_value is None or not raw_value.strip():
        _raise_idempotency_error(
            detail="The Idempotency-Key header is required.",
            code="missing_idempotency_key",
        )
    if len(raw_value) > MAX_IDEMPOTENCY_HEADER_LENGTH:
        _raise_idempotency_error(
            detail="The Idempotency-Key header must contain one canonical UUID.",
            code="invalid_idempotency_key",
        )
    candidate = raw_value.strip()
    if candidate != raw_value:
        _raise_idempotency_error(
            detail="The Idempotency-Key header must contain one canonical UUID.",
            code="invalid_idempotency_key",
        )
    try:
        value = UUID(candidate)
    except (AttributeError, ValueError):
        _raise_idempotency_error(
            detail="The Idempotency-Key header must contain one canonical UUID.",
            code="invalid_idempotency_key",
        )
    if str(value) != candidate:
        _raise_idempotency_error(
            detail="The Idempotency-Key header must contain one canonical UUID.",
            code="invalid_idempotency_key",
        )
    return value


def _validated_payload(
    request: Request,
    *,
    serializer_class: type[
        PlatformAccountInvitationCreateSerializer
        | PlatformAccountInvitationActionSerializer
        | PublicAccountInvitationAcceptanceSerializer
    ],
) -> dict[str, object]:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return cast("dict[str, object]", serializer.validated_data)


def _validated_inventory_query(request: Request) -> dict[str, object]:
    serializer = PlatformAccountInventoryQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return cast("dict[str, object]", serializer.validated_data)


def _first_django_error_code(
    error: DjangoValidationError,
    *,
    fallback: str,
) -> str:
    if hasattr(error, "error_dict"):
        for field_errors in error.error_dict.values():
            if field_errors:
                return str(field_errors[0].code or fallback)
    if hasattr(error, "error_list") and error.error_list:
        return str(error.error_list[0].code or fallback)
    return fallback


def _raise_safe_django_validation(
    error: DjangoValidationError,
    *,
    allowed_fields: frozenset[str],
    detail: str,
) -> Never:
    if not hasattr(error, "error_dict"):
        raise error
    field_names = frozenset(error.error_dict)
    if not field_names or not field_names.issubset(allowed_fields):
        raise error
    code = _first_django_error_code(
        error,
        fallback="account_invitation_input_invalid",
    )
    raise ApiValidationError(
        cast(
            "Any",
            {
                "detail": detail,
                "code": code,
                "errors": {
                    field_name: [str(item.message) for item in field_errors]
                    for field_name, field_errors in error.error_dict.items()
                },
            },
        ),
        code=code,
    ) from error


def _raise_command_error(
    *,
    request: Request,
    operation: str,
    error: Exception,
) -> Never:
    if isinstance(error, InvitationAuthorizationDeniedError):
        raise PermissionDenied(
            _PROTECTED_UNAVAILABLE_DETAIL,
            code=error.reason_code,
        ) from error
    if isinstance(error, InvitationUnavailableError):
        raise NotFound(
            _PROTECTED_UNAVAILABLE_DETAIL,
            code=error.reason_code,
        ) from error
    if isinstance(error, InvitationIdentityConflictError):
        raise InvitationConflict(
            code=error.reason_code,
            errors={
                "non_field_errors": [
                    "The submitted account details are unavailable. No identity "
                    "was changed."
                ]
            },
        ) from error
    conflict_errors: dict[type[Exception], dict[str, list[str]]] = {
        InvitationVersionConflictError: {
            "expected_version": ["Reload the invitation and try again."]
        },
        InvitationRetryConflictError: {
            IDEMPOTENCY_HEADER_NAME: [
                "Use a new Idempotency-Key for a different request."
            ]
        },
        InvitationStateConflictError: {
            "non_field_errors": [
                "The invitation's current state does not permit this action."
            ]
        },
    }
    if type(error) in conflict_errors:
        command_error = cast("InvitationCommandError", error)
        raise InvitationConflict(
            code=command_error.reason_code,
            errors=conflict_errors[type(error)],
        ) from error
    if isinstance(error, DjangoValidationError):
        field_names = frozenset(getattr(error, "error_dict", {}))
        safe_fields = frozenset(
            {
                "email",
                "login_handle",
                "display_name",
                "preferred_language",
                "reason",
                "expected_version",
            }
        )
        if field_names and field_names.issubset(safe_fields):
            _raise_safe_django_validation(
                error,
                allowed_fields=safe_fields,
                detail="The account invitation input is invalid.",
            )
    _safe_dependency_failure(
        request=request,
        operation=operation,
        error=error,
    )


def _mutation_payload(result: AccountInvitationCommandResult) -> dict[str, object]:
    return {
        "id": result.invitation.id,
        "status": result.invitation.status,
        "aggregate_version": result.invitation.aggregate_version,
        "expires_at": result.invitation.expires_at,
        "replayed": result.replayed,
    }


def _inventory_payload(page: AccountInventoryPage) -> dict[str, object]:
    return {
        "inventory_version": page.aggregate_version,
        "items": [
            {
                "id": item.account_id,
                "email": item.email,
                "login_handle": item.login_handle,
                "display_name": item.display_name,
                "kind": item.account_kind,
                "active": item.is_active,
                "email_verified": item.is_email_verified,
                "date_joined": item.date_joined,
                "invitation": (
                    None
                    if item.current_invitation is None
                    else {
                        "id": item.current_invitation.invitation_id,
                        "status": item.current_invitation.status,
                        "aggregate_version": (
                            item.current_invitation.aggregate_version
                        ),
                        "expires_at": item.current_invitation.expires_at,
                        "last_transition_at": (
                            item.current_invitation.last_transition_at
                        ),
                        "delivery_state": (item.current_invitation.delivery_state),
                    }
                ),
            }
            for item in page.items
        ],
        "next_cursor": page.next_cursor,
    }


def _detail_payload(detail: AccountInvitationDetail) -> dict[str, object]:
    delivery = detail.current_delivery
    return {
        "inventory_version": detail.aggregate_version,
        "id": detail.invitation_id,
        "account": {
            "id": detail.account_id,
            "email": detail.email,
            "login_handle": detail.login_handle,
            "display_name": detail.display_name,
            "kind": detail.account_kind,
            "active": detail.is_active,
            "email_verified": detail.is_email_verified,
        },
        "status": detail.status,
        "aggregate_version": detail.invitation_version,
        "expires_at": detail.expires_at,
        "created_at": detail.created_at,
        "last_transition_at": detail.last_transition_at,
        "created_by": {
            "id": detail.created_by_id,
            "display_name": detail.created_by_display_name,
        },
        "delivery": (
            None
            if delivery is None
            else {
                "status": delivery.status,
                "attempt_count": delivery.attempt_count,
                "max_attempts": delivery.max_attempts,
                "last_attempt_at": delivery.last_attempt_at,
                "next_retry_at": delivery.next_retry_at,
                "delivered_at": delivery.delivered_at,
                "safe_error_code": delivery.safe_error_code,
                "reconciliation_state": delivery.reconciliation_state,
            }
        ),
        "transitions": [
            {
                "version": item.version,
                "operation": item.operation,
                "actor": {
                    "id": item.actor_id,
                    "display_name": item.actor_display_name,
                },
                "occurred_at": item.occurred_at,
                "reason": item.reason,
                "source_channel": item.source_channel,
            }
            for item in detail.transitions
        ],
        "delivery_attempts": [
            {
                "attempt_number": item.attempt_number,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
                "outcome": item.outcome,
                "safe_error_code": item.safe_error_code,
                "next_retry_at": item.next_retry_at,
            }
            for item in detail.delivery_attempts
        ],
    }


@method_decorator(never_cache, name="dispatch")
class PlatformAccountInventoryView(APIView):
    """Expose platform account inventory through the HTTP API."""

    @extend_schema(
        operation_id="identity_list_platform_accounts",
        parameters=[PlatformAccountInventoryQuerySerializer],
        responses={
            200: PlatformAccountInventorySerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The closed account-inventory query is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Fresh platform administration is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The cursor is stale or the complete bounded result is unavailable."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "The complete audited account inventory is unavailable."
            ),
        },
    )
    def get(self, request: Request) -> Response:
        """List the platform accounts.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        ApiValidationError
            If the request payload violates the endpoint contract.
        InvitationConflict
            If the operation encounters a invitation conflict condition.
        PermissionDenied
            If the caller lacks permission for the requested scope.
        """
        actor = _active_platform_administrator(request, require_step_up=False)
        query = _validated_inventory_query(request)
        try:
            page = load_platform_account_inventory(
                actor=actor,
                audit_hook=append_platform_account_read_audit,
                correlation_id=_request_id(request),
                source_channel="api",
                search=query.get("search"),
                search_mode=query.get("search_mode", "prefix"),
                kind=query.get("kind"),
                state=query.get("state"),
                cursor=query.get("cursor"),
                page_size=query.get("page_size", 100),
            )
        except PlatformAccountInventoryDeniedError as error:
            raise PermissionDenied(
                _PROTECTED_UNAVAILABLE_DETAIL,
                code=error.code,
            ) from error
        except PlatformAccountInventoryInputError as error:
            raise ApiValidationError(
                cast(
                    "Any",
                    {
                        "detail": "The account inventory request is invalid.",
                        "code": error.detail_code,
                        "errors": {
                            error.field_name: ["Review this value and try again."]
                        },
                    },
                ),
                code=error.detail_code,
            ) from error
        except (
            PlatformAccountInventoryCursorStaleError,
            PlatformAccountInventoryLimitExceededError,
        ) as error:
            raise InvitationConflict(
                code=error.code,
                errors={
                    "non_field_errors": [
                        "Reload the complete account inventory and try again."
                    ]
                },
            ) from error
        except PlatformAccountInventoryUnavailableError as error:
            _safe_dependency_failure(
                request=request,
                operation="account_inventory_read",
                error=error,
            )
        return Response(
            PlatformAccountInventorySerializer(instance=_inventory_payload(page)).data
        )


@method_decorator(never_cache, name="dispatch")
class PlatformAccountInvitationCreateView(APIView):
    """Expose platform account invitation create through the HTTP API."""

    @extend_schema(
        operation_id="identity_create_platform_account_invitation",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=PlatformAccountInvitationCreateSerializer,
        responses={
            200: PlatformAccountInvitationMutationSerializer,
            201: PlatformAccountInvitationMutationSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The header or closed invitation input is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Fresh platform administration or required step-up is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The identity, version, state, or retry key conflicts."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A required identity dependency is unavailable."
            ),
        },
    )
    def post(self, request: Request) -> Response:
        """Create the platform account invitation.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _active_platform_administrator(request, require_step_up=True)
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        retry_key = _idempotency_key(request)
        payload = _validated_payload(
            request,
            serializer_class=PlatformAccountInvitationCreateSerializer,
        )
        correlation_id = _request_id(request)
        try:
            result = create_platform_account_invitation(
                actor=actor,
                email=payload["email"],
                login_handle=payload.get("login_handle"),
                display_name=payload.get("display_name"),
                preferred_language=payload.get("preferred_language"),
                reason=payload["reason"],
                expected_version=payload["expected_version"],
                retry_key=retry_key,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        except (
            DatabaseError,
            DjangoValidationError,
            InvitationCommandError,
            RuntimeError,
        ) as error:
            _raise_command_error(
                request=request,
                operation="account_invitation_create",
                error=error,
            )
        return Response(
            PlatformAccountInvitationMutationSerializer(
                instance=_mutation_payload(result)
            ).data,
            status=(status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED),
        )


@method_decorator(never_cache, name="dispatch")
class PlatformAccountInvitationDetailView(APIView):
    """Expose platform account invitation detail through the HTTP API."""

    @extend_schema(
        operation_id="identity_retrieve_platform_account_invitation",
        responses={
            200: PlatformAccountInvitationDetailSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The detail request contains unsupported input."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Fresh platform administration is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The invitation is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The bounded invitation timeline cannot be projected."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "The complete audited projection is unavailable."
            ),
        },
    )
    def get(self, request: Request, invitation_id: UUID) -> Response:
        """Retrieve the platform account invitation.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        invitation_id : UUID
            The invitation identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        ApiValidationError
            If the request payload violates the endpoint contract.
        InvitationConflict
            If the operation encounters a invitation conflict condition.
        NotFound
            If the scoped resource is unavailable to the caller.
        PermissionDenied
            If the caller lacks permission for the requested scope.
        """
        actor = _active_platform_administrator(request, require_step_up=False)
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        try:
            detail = load_platform_account_invitation_detail(
                actor=actor,
                invitation_id=invitation_id,
                audit_hook=append_platform_account_read_audit,
                correlation_id=_request_id(request),
                source_channel="api",
            )
        except PlatformAccountInventoryDeniedError as error:
            raise PermissionDenied(
                _PROTECTED_UNAVAILABLE_DETAIL,
                code=error.code,
            ) from error
        except PlatformAccountInvitationNotFoundError as error:
            raise NotFound(
                _PROTECTED_UNAVAILABLE_DETAIL,
                code=error.code,
            ) from error
        except PlatformAccountInventoryInputError as error:
            raise ApiValidationError(
                cast(
                    "Any",
                    {
                        "detail": "The invitation request is invalid.",
                        "code": error.detail_code,
                        "errors": {
                            error.field_name: ["Review this value and try again."]
                        },
                    },
                ),
                code=error.detail_code,
            ) from error
        except (
            PlatformAccountInventoryCursorStaleError,
            PlatformAccountInventoryLimitExceededError,
        ) as error:
            raise InvitationConflict(
                code=error.code,
                errors={
                    "non_field_errors": [
                        "The complete bounded invitation timeline is unavailable."
                    ]
                },
            ) from error
        except PlatformAccountInventoryUnavailableError as error:
            _safe_dependency_failure(
                request=request,
                operation="account_invitation_read",
                error=error,
            )
        return Response(
            PlatformAccountInvitationDetailSerializer(
                instance=_detail_payload(detail)
            ).data
        )


class _PlatformAccountInvitationActionView(APIView):
    operation = ""

    def post(self, request: Request, invitation_id: UUID) -> Response:
        actor = _active_platform_administrator(request, require_step_up=True)
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        retry_key = _idempotency_key(request)
        payload = _validated_payload(
            request,
            serializer_class=PlatformAccountInvitationActionSerializer,
        )
        correlation_id = _request_id(request)
        command = (
            reissue_platform_account_invitation
            if self.operation == "reissue"
            else revoke_platform_account_invitation
        )
        try:
            result = command(
                actor=actor,
                invitation_id=invitation_id,
                expected_version=payload["expected_version"],
                reason=payload["reason"],
                retry_key=retry_key,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        except (
            DatabaseError,
            DjangoValidationError,
            InvitationCommandError,
            RuntimeError,
        ) as error:
            _raise_command_error(
                request=request,
                operation=f"account_invitation_{self.operation}",
                error=error,
            )
        return Response(
            PlatformAccountInvitationMutationSerializer(
                instance=_mutation_payload(result)
            ).data
        )


@method_decorator(never_cache, name="dispatch")
class PlatformAccountInvitationReissueView(_PlatformAccountInvitationActionView):
    """Expose platform account invitation reissue through the HTTP API."""

    operation = "reissue"

    @extend_schema(
        operation_id="identity_reissue_platform_account_invitation",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=PlatformAccountInvitationActionSerializer,
        responses={
            200: PlatformAccountInvitationMutationSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The header or closed reissue input is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Fresh platform administration or required step-up is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The invitation is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The invitation version, state, or retry key conflicts."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A required identity dependency is unavailable."
            ),
        },
    )
    def post(self, request: Request, invitation_id: UUID) -> Response:
        """Reissue the platform account invitation.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        invitation_id : UUID
            The invitation identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        return super().post(request, invitation_id)


@method_decorator(never_cache, name="dispatch")
class PlatformAccountInvitationRevokeView(_PlatformAccountInvitationActionView):
    """Expose platform account invitation revoke through the HTTP API."""

    operation = "revoke"

    @extend_schema(
        operation_id="identity_revoke_platform_account_invitation",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=PlatformAccountInvitationActionSerializer,
        responses={
            200: PlatformAccountInvitationMutationSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The header or closed revocation input is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Fresh platform administration or required step-up is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The invitation is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The invitation version, state, or retry key conflicts."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A required identity dependency is unavailable."
            ),
        },
    )
    def post(self, request: Request, invitation_id: UUID) -> Response:
        """Revoke the platform account invitation.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        invitation_id : UUID
            The invitation identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        return super().post(request, invitation_id)


@method_decorator(never_cache, name="dispatch")
class PublicAccountInvitationAcceptanceView(APIView):
    # Acceptance authority is the single-use bearer challenge, never an
    # unrelated Django session. Ignoring ambient session authentication keeps
    # the public JSON flow CSRF-independent without turning a session into
    # invitation authority.
    """Expose public account invitation acceptance through the HTTP API."""

    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="identity_accept_platform_account_invitation",
        auth=[],
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=PublicAccountInvitationAcceptanceSerializer,
        responses={
            200: PublicAccountInvitationAcceptanceResultSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The non-enumerating acceptance input is invalid."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The retry key was reused with a different recipient password."
            ),
            (429, PROBLEM_CONTENT_TYPE): _problem_response(
                "The bounded acceptance attempt limit was reached."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A required identity dependency is unavailable."
            ),
        },
    )
    def post(self, request: Request) -> Response:
        # Reject every query parameter without reflecting attacker-controlled
        # names. The invitation secret belongs in one JSON property, never a URL.
        """Accept the platform account invitation.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        ApiValidationError
            If the request payload violates the endpoint contract.
        InvitationAcceptanceRateLimited
            If the operation encounters a invitation acceptance rate limited
            condition.
        InvitationConflict
            If the operation encounters a invitation conflict condition.
        """
        if request.query_params:
            raise ApiValidationError(
                cast(
                    "Any",
                    {
                        "detail": _PUBLIC_INVALID_DETAIL,
                        "code": "unknown_input_field",
                        "errors": {
                            "non_field_errors": [
                                "Remove unsupported request parameters."
                            ]
                        },
                    },
                ),
                code="unknown_input_field",
            )
        # The retry header is deliberately parsed before request.data so an
        # invalid header never causes a C4 bearer/password body to be parsed.
        retry_key = _idempotency_key(request)
        payload = _validated_payload(
            request,
            serializer_class=PublicAccountInvitationAcceptanceSerializer,
        )
        correlation_id = _request_id(request)
        try:
            result = accept_platform_account_invitation(
                raw_token=cast("str", payload["raw_token"]),
                new_password=cast("str", payload["new_password1"]),
                retry_key=retry_key,
                correlation_id=correlation_id,
                request_fingerprint=request_fingerprint(request._request),
                request_id=correlation_id,
                source_channel="api",
            )
        except (
            InvitationChallengeInvalidError,
            InvitationStateConflictError,
            InvitationUnavailableError,
        ) as error:
            raise ApiValidationError(
                cast(
                    "Any",
                    {
                        "detail": _PUBLIC_INVALID_DETAIL,
                        "code": InvitationChallengeInvalidError.reason_code,
                        "errors": {
                            "raw_token": [
                                "The invitation code is invalid or has expired."
                            ]
                        },
                    },
                ),
                code=InvitationChallengeInvalidError.reason_code,
            ) from error
        except InvitationRetryConflictError as error:
            raise InvitationConflict(
                code=error.reason_code,
                errors={
                    IDEMPOTENCY_HEADER_NAME: [
                        "Reload the clean acceptance form and use a new "
                        "Idempotency-Key."
                    ]
                },
            ) from error
        except DjangoValidationError as error:
            source_code = _first_django_error_code(
                error,
                fallback="invitation_password_invalid",
            )
            if source_code == "identity_rate_limited":
                raise InvitationAcceptanceRateLimited from None
            code, message = _SAFE_PASSWORD_VALIDATION_ERRORS.get(
                source_code,
                _GENERIC_PASSWORD_VALIDATION,
            )
            raise ApiValidationError(
                cast(
                    "Any",
                    {
                        "detail": _PUBLIC_INVALID_DETAIL,
                        "code": code,
                        "errors": {"new_password1": [message]},
                    },
                ),
                code=code,
            ) from None
        except (DatabaseError, InvitationDependencyUnavailableError) as error:
            _safe_dependency_failure(
                request=request,
                operation="account_invitation_accept",
                error=error,
            )
        return Response(
            PublicAccountInvitationAcceptanceResultSerializer(
                instance={
                    "accepted": True,
                    "next": "sign_in",
                    "replayed": result.replayed,
                }
            ).data
        )


__all__ = [
    "PlatformAccountInventoryView",
    "PlatformAccountInvitationCreateView",
    "PlatformAccountInvitationDetailView",
    "PlatformAccountInvitationReissueView",
    "PlatformAccountInvitationRevokeView",
    "PublicAccountInvitationAcceptanceView",
]
