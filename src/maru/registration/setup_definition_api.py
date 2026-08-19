"""Canonical strict v1 API adapters for Page 10 definition commands."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Never, cast
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.authorization.policy import decide, resolve_edition_target
from maru.core.api_input import reject_unknown_fields
from maru.core.problems import DependencyUnavailable
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.registration.models import RegistrationSetupCommandReceipt
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupCommandError,
    RegistrationSetupDependencyError,
    RegistrationSetupLimitExceededError,
    RegistrationSetupSourceUnavailableError,
    RegistrationSetupStateConflictError,
    start_registration_setup,
)
from maru.registration.setup_definition_commands import (
    RegistrationDefinitionCommandResult,
    RegistrationSetupMinorPolicyUnavailableError,
    RegistrationSetupProductUnavailableError,
    RegistrationSetupProfileFieldUnavailableError,
    RegistrationSetupQuestionUnavailableError,
    create_admission_product,
    create_registration_profile_extension_field,
    create_registration_question,
    delete_admission_product,
    delete_registration_question,
    move_admission_product,
    move_registration_profile_extension_field,
    move_registration_question,
    remove_minor_registration_policy,
    retire_registration_profile_extension_field,
    set_minor_registration_policy,
    update_admission_product,
    update_registration_profile_extension_field,
    update_registration_question,
)
from maru.registration.setup_definition_serializers import (
    COMMAND_SERIALIZER_BY_OPERATION,
    PROFILE_COMMAND_SERIALIZER_BY_OPERATION,
    RegistrationDefinitionMutationSerializer,
    RegistrationProfileExtensionCatalogSerializer,
    RegistrationProfileFieldCreateSerializer,
    RegistrationSetupProblemSerializer,
    RegistrationSetupStartCommandSerializer,
    RegistrationSetupStartResultSerializer,
    RegistrationSetupStartWorkspaceSerializer,
)
from maru.registration.setup_queries import (
    RegistrationSetupSourceOption,
    get_registration_setup_workspace,
)
from maru.registration.setup_section_commands import (
    RegistrationSectionCommandResult,
    RegistrationSetupConfigurationUnavailableError,
    RegistrationSetupSectionUnavailableError,
    create_registration_section,
    delete_registration_section,
    move_registration_section,
    update_registration_section,
)

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"
IDEMPOTENCY_HEADER_NAME = "Idempotency-Key"
MAX_IDEMPOTENCY_HEADER_LENGTH = 64
CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_PROTECTED_DETAIL = "Registration setup is unavailable."


def _problem_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(
        response=RegistrationSetupProblemSerializer,
        description=description,
    )


_IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name=IDEMPOTENCY_HEADER_NAME,
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    pattern=CANONICAL_UUID_PATTERN,
    description=(
        "Canonical lower-case UUID. Reuse with the same actor, exact scope, "
        "operation, version, and normalized input recovers the first result. "
        "The key is not accepted in JSON."
    ),
)

_IDEMPOTENT_REPLAY_RESPONSE_PARAMETER = OpenApiParameter(
    name="Idempotent-Replay",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.HEADER,
    required=True,
    enum=("false", "true"),
    response=(200, 201),
    description=(
        "Whether this response recovered the original receipt for an exact "
        "Idempotency-Key replay."
    ),
)


_CONFIGURATION_COMMAND_REQUEST = PolymorphicProxySerializer(
    component_name="RegistrationConfigurationDefinitionCommand",
    serializers=cast(
        dict[
            str,
            serializers.Serializer[Any] | type[serializers.Serializer[Any]],
        ],
        COMMAND_SERIALIZER_BY_OPERATION,
    ),
    resource_type_field_name="operation",
)

_PROFILE_COMMAND_REQUEST = PolymorphicProxySerializer(
    component_name="RegistrationProfileFieldCommand",
    serializers=cast(
        dict[
            str,
            serializers.Serializer[Any] | type[serializers.Serializer[Any]],
        ],
        PROFILE_COMMAND_SERIALIZER_BY_OPERATION,
    ),
    resource_type_field_name="operation",
)


class RegistrationSetupConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The registration setup request conflicts with current state."
    default_code = "registration_setup_conflict"

    def __init__(self, *, code: str) -> None:
        super().__init__(
            detail=cast(
                Any,
                {
                    "detail": self.default_detail,
                    "code": code,
                    "errors": {
                        "non_field_errors": [
                            "Reload the exact edition setup and review this action."
                        ]
                    },
                },
            ),
            code=code,
        )


def _request_id(request: Request) -> UUID:
    candidate = getattr(request, "correlation_id", None)
    if isinstance(candidate, str):
        try:
            return UUID(candidate)
        except ValueError:
            pass
    return uuid4()


def _dependency_failure(
    *,
    request: Request,
    operation: str,
    error: Exception,
) -> Never:
    logger.error(
        "Registration setup API dependency failed",
        extra={
            "correlation_id": str(_request_id(request)),
            "operation": operation,
            "failure_class": type(error).__name__,
        },
    )
    raise DependencyUnavailable from error


def _configuration_manager(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> tuple[Account, UUID]:
    """Resolve fresh exact-edition authority before parsing caller input."""

    principal = request.user
    if not isinstance(principal, Account) or not principal.is_authenticated:
        raise PermissionDenied(
            _PROTECTED_DETAIL,
            code=RegistrationSetupAuthorizationDeniedError.reason_code,
        )
    try:
        actor = Account.objects.filter(id=principal.id, is_active=True).first()
        series_id = (
            EventEdition.objects.filter(
                id=edition_id,
                organization_id=organization_id,
                series__organization_id=organization_id,
            )
            .values_list("series_id", flat=True)
            .first()
        )
        target = resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        decision = (
            decide(
                principal=actor,
                capability_code="registration.manage_configuration",
                resource=target,
            )
            if actor is not None and target is not None and series_id is not None
            else None
        )
    except (DatabaseError, RuntimeError) as error:
        _dependency_failure(
            request=request,
            operation="registration_setup_authorize",
            error=error,
        )
    if actor is None or series_id is None or decision is None or not decision.allowed:
        raise PermissionDenied(
            _PROTECTED_DETAIL,
            code=(
                decision.reason_code
                if decision is not None
                else RegistrationSetupAuthorizationDeniedError.reason_code
            ),
        )
    return actor, series_id


def _idempotency_key(request: Request) -> UUID:
    raw_value = request.headers.get(IDEMPOTENCY_HEADER_NAME)
    if raw_value is None or not raw_value.strip():
        raise ApiValidationError(
            cast(
                Any,
                {
                    "detail": "The Idempotency-Key header is required.",
                    "code": "missing_idempotency_key",
                    "errors": {
                        IDEMPOTENCY_HEADER_NAME: [
                            "Provide one canonical lower-case UUID."
                        ]
                    },
                },
            ),
            code="missing_idempotency_key",
        )
    if len(raw_value) > MAX_IDEMPOTENCY_HEADER_LENGTH:
        candidate = ""
    else:
        candidate = raw_value.strip()
    try:
        value = UUID(candidate)
    except (AttributeError, ValueError):
        value = None
    if value is None or str(value) != candidate:
        raise ApiValidationError(
            cast(
                Any,
                {
                    "detail": (
                        "The Idempotency-Key header must contain one canonical UUID."
                    ),
                    "code": "invalid_idempotency_key",
                    "errors": {
                        IDEMPOTENCY_HEADER_NAME: [
                            "Use lower-case hexadecimal with canonical hyphens."
                        ]
                    },
                },
            ),
            code="invalid_idempotency_key",
        )
    return value


def _closed_command_payload(
    request: Request,
    *,
    serializer_by_operation: Mapping[str, type[serializers.Serializer[Any]]],
) -> tuple[str, dict[str, Any]]:
    data = request.data
    if not isinstance(data, Mapping):
        raise ApiValidationError(
            cast(
                Any,
                {
                    "detail": "The command body must be one JSON object.",
                    "code": "invalid_registration_setup_command",
                },
            ),
            code="invalid_registration_setup_command",
        )
    operation = data.get("operation")
    operation_name = operation if isinstance(operation, str) else None
    serializer_class = (
        serializer_by_operation.get(operation_name)
        if operation_name is not None
        else None
    )
    if operation_name is None or serializer_class is None:
        raise ApiValidationError(
            cast(
                Any,
                {
                    "detail": "Choose one documented registration setup operation.",
                    "code": "unknown_registration_setup_operation",
                    "errors": {"operation": ["Choose one documented operation."]},
                },
            ),
            code="unknown_registration_setup_operation",
        )
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return operation_name, cast(dict[str, Any], serializer.validated_data)


def _django_validation(error: DjangoValidationError) -> Never:
    errors: dict[str, list[str]]
    if hasattr(error, "message_dict"):
        errors = {
            str(field): [str(message) for message in messages]
            for field, messages in error.message_dict.items()
        }
    else:
        errors = {"non_field_errors": [str(message) for message in error.messages]}
    code = "invalid_registration_setup_command"
    if hasattr(error, "error_dict"):
        for field_errors in error.error_dict.values():
            if field_errors:
                code = str(field_errors[0].code or code)
                break
    elif hasattr(error, "error_list") and error.error_list:
        code = str(error.error_list[0].code or code)
    raise ApiValidationError(
        cast(
            Any,
            {
                "detail": "The registration setup command is invalid.",
                "code": code,
                "errors": errors,
            },
        ),
        code=code,
    ) from error


_UNAVAILABLE_ERRORS = (
    RegistrationSetupConfigurationUnavailableError,
    RegistrationSetupSectionUnavailableError,
    RegistrationSetupQuestionUnavailableError,
    RegistrationSetupProductUnavailableError,
    RegistrationSetupMinorPolicyUnavailableError,
    RegistrationSetupProfileFieldUnavailableError,
    RegistrationSetupSourceUnavailableError,
)


def _command_failure(
    *,
    request: Request,
    operation: str,
    error: Exception,
) -> Never:
    if isinstance(error, RegistrationSetupAuthorizationDeniedError):
        raise PermissionDenied(_PROTECTED_DETAIL, code=error.reason_code) from error
    if isinstance(error, _UNAVAILABLE_ERRORS):
        raise NotFound(_PROTECTED_DETAIL, code=error.reason_code) from error
    if isinstance(error, RegistrationSetupDependencyError):
        _dependency_failure(request=request, operation=operation, error=error)
    if isinstance(error, DjangoValidationError):
        _django_validation(error)
    if isinstance(error, RegistrationSetupCommandError):
        raise RegistrationSetupConflict(code=error.reason_code) from error
    if isinstance(error, (DatabaseError, RuntimeError)):
        _dependency_failure(request=request, operation=operation, error=error)
    _dependency_failure(request=request, operation=operation, error=error)


def _common_command_arguments(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    payload: Mapping[str, Any],
    retry_key: UUID,
    correlation_id: UUID,
) -> dict[str, Any]:
    return {
        "actor": actor,
        "organization_id": organization_id,
        "series_id": series_id,
        "edition_id": edition_id,
        "expected_version": payload["expected_version"],
        "reason": payload["reason"],
        "retry_key": retry_key,
        "correlation_id": correlation_id,
        "request_id": correlation_id,
        "source_channel": "api",
    }


def _run_configuration_command(  # noqa: PLR0911, PLR0912
    *,
    operation: str,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    configuration_id: UUID,
    payload: Mapping[str, Any],
    retry_key: UUID,
    correlation_id: UUID,
) -> RegistrationDefinitionCommandResult | RegistrationSectionCommandResult:
    common = _common_command_arguments(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        payload=payload,
        retry_key=retry_key,
        correlation_id=correlation_id,
    )
    scoped = {**common, "configuration_id": configuration_id}
    if operation == "section.create":
        return create_registration_section(
            **scoped,
            key=payload["key"],
            title=payload["title"],
            description=payload["description"],
            after_section_id=payload.get("after_section_id"),
        )
    if operation == "section.update":
        return update_registration_section(
            **scoped,
            section_id=payload["section_id"],
            key=payload["key"],
            title=payload["title"],
            description=payload["description"],
        )
    if operation == "section.move":
        return move_registration_section(
            **scoped,
            section_id=payload["section_id"],
            after_section_id=payload.get("after_section_id"),
        )
    if operation == "section.remove":
        return delete_registration_section(
            **scoped,
            section_id=payload["section_id"],
        )
    if operation == "question.create":
        return create_registration_question(
            **scoped,
            key=payload["key"],
            label=payload["label"],
            help_text=payload["help_text"],
            field_type=payload["field_type"],
            required=payload["required"],
            options=payload["options"],
            purpose=payload["purpose"],
            visibility=payload["visibility"],
            classification=payload["classification"],
            condition_question_key=payload["condition_question_key"],
            condition_value=payload["condition_value"],
            section_id=payload.get("section_id"),
            after_question_id=payload.get("after_question_id"),
        )
    if operation == "question.update":
        return update_registration_question(
            **scoped,
            question_id=payload["question_id"],
            key=payload["key"],
            label=payload["label"],
            help_text=payload["help_text"],
            field_type=payload["field_type"],
            required=payload["required"],
            options=payload["options"],
            purpose=payload["purpose"],
            visibility=payload["visibility"],
            classification=payload["classification"],
            condition_question_key=payload["condition_question_key"],
            condition_value=payload["condition_value"],
            section_id=payload.get("section_id"),
        )
    if operation == "question.move":
        return move_registration_question(
            **scoped,
            question_id=payload["question_id"],
            after_question_id=payload.get("after_question_id"),
        )
    if operation == "question.remove":
        return delete_registration_question(
            **scoped,
            question_id=payload["question_id"],
        )
    if operation == "product.create":
        return create_admission_product(
            **scoped,
            code=payload["code"],
            name=payload["name"],
            description=payload["description"],
            price_minor=payload["price_minor"],
            capacity=payload["capacity"],
            capacity_ceiling=payload.get("capacity_ceiling"),
            entitlement_code=payload["entitlement_code"],
            entitlement_name=payload["entitlement_name"],
            sales_open_at=payload.get("sales_open_at"),
            sales_close_at=payload.get("sales_close_at"),
            required_capacity_codes=payload["required_capacity_codes"],
            eligibility_explanation=payload["eligibility_explanation"],
            waitlist_enabled=payload["waitlist_enabled"],
            payment_window_minutes=payload.get("payment_window_minutes"),
            after_product_id=payload.get("after_product_id"),
        )
    if operation == "product.update":
        return update_admission_product(
            **scoped,
            product_id=payload["product_id"],
            code=payload["code"],
            name=payload["name"],
            description=payload["description"],
            price_minor=payload["price_minor"],
            capacity=payload["capacity"],
            capacity_ceiling=payload.get("capacity_ceiling"),
            entitlement_code=payload["entitlement_code"],
            entitlement_name=payload["entitlement_name"],
            sales_open_at=payload.get("sales_open_at"),
            sales_close_at=payload.get("sales_close_at"),
            required_capacity_codes=payload["required_capacity_codes"],
            eligibility_explanation=payload["eligibility_explanation"],
            waitlist_enabled=payload["waitlist_enabled"],
            payment_window_minutes=payload.get("payment_window_minutes"),
        )
    if operation == "product.move":
        return move_admission_product(
            **scoped,
            product_id=payload["product_id"],
            after_product_id=payload.get("after_product_id"),
        )
    if operation == "product.remove":
        return delete_admission_product(
            **scoped,
            product_id=payload["product_id"],
        )
    if operation == "minor_policy.set":
        return set_minor_registration_policy(
            **scoped,
            enabled=payload["enabled"],
            minor_age_threshold=payload["minor_age_threshold"],
            guardian_notice_version=payload["guardian_notice_version"],
            jurisdiction_code=payload["jurisdiction_code"],
            review_reference=payload["review_reference"],
        )
    if operation == "minor_policy.remove":
        return remove_minor_registration_policy(**scoped)
    raise RegistrationSetupStateConflictError()


def _run_profile_command(
    *,
    operation: str,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    field_id: UUID,
    payload: Mapping[str, Any],
    retry_key: UUID,
    correlation_id: UUID,
) -> RegistrationDefinitionCommandResult:
    common = _common_command_arguments(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        payload=payload,
        retry_key=retry_key,
        correlation_id=correlation_id,
    )
    if operation == "profile_field.update":
        return update_registration_profile_extension_field(
            **common,
            field_id=field_id,
            key=payload["key"],
            label=payload["label"],
            help_text=payload["help_text"],
            field_type=payload["field_type"],
            options=payload["options"],
            purpose=payload["purpose"],
            classification=payload["classification"],
            audience_policy=payload["audience_policy"],
            audience_department_id=payload.get("audience_department_id"),
            writer_policy=payload["writer_policy"],
            required=payload["required"],
        )
    if operation == "profile_field.move":
        return move_registration_profile_extension_field(
            **common,
            field_id=field_id,
            after_field_id=payload.get("after_field_id"),
        )
    if operation == "profile_field.retire":
        return retire_registration_profile_extension_field(
            **common,
            field_id=field_id,
        )
    raise RegistrationSetupStateConflictError()


def _mutation_response(
    result: RegistrationDefinitionCommandResult | RegistrationSectionCommandResult,
    *,
    created: bool,
) -> Response:
    if isinstance(result, RegistrationSectionCommandResult):
        payload: dict[str, object] = {
            "setup_id": result.setup_id,
            "receipt_id": result.receipt_id,
            "target_id": result.section_id,
            "resulting_version": result.resulting_version,
            "action": result.action,
            "configuration_id": result.configuration_id,
            "configuration_content_digest": result.configuration_content_digest,
            "replayed": result.replayed,
        }
    else:
        payload = {
            "setup_id": result.setup_id,
            "receipt_id": result.receipt_id,
            "target_id": result.target_id,
            "resulting_version": result.resulting_version,
            "action": result.action,
            "configuration_id": result.configuration_id,
            "configuration_content_digest": result.configuration_content_digest,
            "replayed": result.replayed,
        }
    response = Response(
        RegistrationDefinitionMutationSerializer(instance=payload).data,
        status=(
            status.HTTP_201_CREATED
            if created and not result.replayed
            else status.HTTP_200_OK
        ),
    )
    response["Idempotent-Replay"] = "true" if result.replayed else "false"
    return response


def _setup_source_payload(
    source: RegistrationSetupSourceOption,
) -> dict[str, object]:
    return {
        "source_kind": source.source_kind,
        "source_id": source.source_id,
        "name": source.name,
        "version": source.version,
        "content_digest": source.content_digest,
        "source_edition_id": source.source_edition_id,
        "source_edition_name": source.source_edition_name,
    }


@method_decorator(never_cache, name="dispatch")
class RegistrationSetupStartView(APIView):
    @extend_schema(
        operation_id="registration_get_setup_start_choices",
        responses={
            200: RegistrationSetupStartWorkspaceSerializer,
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Exact-edition setup authority is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "A bounded coherent setup projection cannot be produced."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "The audited setup projection is temporarily unavailable."
            ),
        },
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        actor, series_id = _configuration_manager(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        correlation_id = _request_id(request)
        try:
            workspace = get_registration_setup_workspace(
                actor=actor,
                organization_id=organization_id,
                series_id=series_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        except RegistrationSetupAuthorizationDeniedError as error:
            raise PermissionDenied(_PROTECTED_DETAIL, code=error.reason_code) from error
        except (
            RegistrationSetupLimitExceededError,
            RegistrationSetupStateConflictError,
        ) as error:
            raise RegistrationSetupConflict(code=error.reason_code) from error
        except (DatabaseError, RegistrationSetupCommandError, RuntimeError) as error:
            _dependency_failure(
                request=request,
                operation="setup_start_choices",
                error=error,
            )
        payload = {
            "organization_id": workspace.organization_id,
            "series_id": workspace.series_id,
            "edition_id": workspace.edition_id,
            "setup_state": workspace.setup_state,
            "aggregate_version": workspace.aggregate_version,
            "platform_starters": [
                _setup_source_payload(source) for source in workspace.platform_starters
            ],
            "published_templates": [
                _setup_source_payload(source)
                for source in workspace.published_templates
            ],
            "prior_configurations": [
                _setup_source_payload(source)
                for source in workspace.prior_configurations
            ],
        }
        return Response(
            RegistrationSetupStartWorkspaceSerializer(instance=payload).data
        )

    @extend_schema(
        operation_id="registration_start_governed_setup",
        parameters=[_IDEMPOTENCY_PARAMETER, _IDEMPOTENT_REPLAY_RESPONSE_PARAMETER],
        request=RegistrationSetupStartCommandSerializer,
        responses={
            200: RegistrationSetupStartResultSerializer,
            201: RegistrationSetupStartResultSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The header or closed setup-start body is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Exact-edition setup authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact source version is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The lifecycle, version, or retry key conflicts."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "Complete atomic setup evidence is temporarily unavailable."
            ),
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        actor, series_id = _configuration_manager(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        retry_key = _idempotency_key(request)
        serializer = RegistrationSetupStartCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = cast(dict[str, Any], serializer.validated_data)
        correlation_id = _request_id(request)
        try:
            result = start_registration_setup(
                actor=actor,
                organization_id=organization_id,
                series_id=series_id,
                edition_id=edition_id,
                source_kind=payload["source_kind"],
                source_id=payload.get("source_id"),
                name=payload["name"],
                opens_at=payload.get("opens_at"),
                closes_at=payload.get("closes_at"),
                capacity=payload.get("capacity"),
                capacity_ceiling=payload.get("capacity_ceiling"),
                currency=payload.get("currency"),
                minimum_age=payload.get("minimum_age"),
                default_payment_window_minutes=payload.get(
                    "default_payment_window_minutes"
                ),
                waitlist_enabled=payload.get("waitlist_enabled"),
                automatic_waitlist_promotion=payload.get(
                    "automatic_waitlist_promotion"
                ),
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
            RegistrationSetupCommandError,
            RuntimeError,
        ) as error:
            _command_failure(
                request=request,
                operation="setup.start",
                error=error,
            )
        response = Response(
            RegistrationSetupStartResultSerializer(instance=result).data,
            status=(status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED),
        )
        response["Idempotent-Replay"] = "true" if result.replayed else "false"
        return response


@method_decorator(never_cache, name="dispatch")
class RegistrationConfigurationCommandView(APIView):
    @extend_schema(
        operation_id="registration_apply_configuration_definition_command",
        parameters=[_IDEMPOTENCY_PARAMETER, _IDEMPOTENT_REPLAY_RESPONSE_PARAMETER],
        request=_CONFIGURATION_COMMAND_REQUEST,
        responses={
            200: RegistrationDefinitionMutationSerializer,
            201: RegistrationDefinitionMutationSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The header, discriminator, or closed command body is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Exact-edition configuration authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact governed definition is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The version, lifecycle, dependency, or retry key conflicts."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "Complete atomic setup evidence is temporarily unavailable."
            ),
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        configuration_id: UUID,
    ) -> Response:
        actor, series_id = _configuration_manager(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        retry_key = _idempotency_key(request)
        operation, payload = _closed_command_payload(
            request,
            serializer_by_operation=COMMAND_SERIALIZER_BY_OPERATION,
        )
        correlation_id = _request_id(request)
        try:
            result = _run_configuration_command(
                operation=operation,
                actor=actor,
                organization_id=organization_id,
                series_id=series_id,
                edition_id=edition_id,
                configuration_id=configuration_id,
                payload=payload,
                retry_key=retry_key,
                correlation_id=correlation_id,
            )
        except (
            DatabaseError,
            DjangoValidationError,
            RegistrationSetupCommandError,
            RuntimeError,
        ) as error:
            _command_failure(
                request=request,
                operation=operation,
                error=error,
            )
        created = operation.endswith(".create") or (
            result.action == RegistrationSetupCommandReceipt.Action.MINOR_POLICY_CREATED
        )
        return _mutation_response(result, created=created)


@method_decorator(never_cache, name="dispatch")
class RegistrationProfileExtensionFieldCollectionView(APIView):
    @extend_schema(
        operation_id="registration_list_profile_extension_fields",
        responses={
            200: RegistrationProfileExtensionCatalogSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The closed list input is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Exact-edition catalog authority is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "A bounded coherent catalog cannot be projected."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "The complete audited catalog is temporarily unavailable."
            ),
        },
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        actor, series_id = _configuration_manager(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        correlation_id = _request_id(request)
        try:
            workspace = get_registration_setup_workspace(
                actor=actor,
                organization_id=organization_id,
                series_id=series_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        except RegistrationSetupAuthorizationDeniedError as error:
            raise PermissionDenied(_PROTECTED_DETAIL, code=error.reason_code) from error
        except (
            RegistrationSetupLimitExceededError,
            RegistrationSetupStateConflictError,
        ) as error:
            raise RegistrationSetupConflict(code=error.reason_code) from error
        except (DatabaseError, RegistrationSetupCommandError, RuntimeError) as error:
            _dependency_failure(
                request=request,
                operation="profile_field_catalog_read",
                error=error,
            )
        payload = {
            "organization_id": workspace.organization_id,
            "edition_id": workspace.edition_id,
            "aggregate_version": workspace.aggregate_version,
            "fields": [
                {
                    "id": field.id,
                    "key": field.key,
                    "version": field.version,
                    "label": field.label,
                    "help_text": field.help_text,
                    "field_type": field.field_type,
                    "options": list(field.options),
                    "purpose": field.purpose,
                    "classification": field.classification,
                    "audience_policy": field.audience_policy,
                    "audience_department_id": field.audience_department_id,
                    "audience_department_name": field.audience_department_name,
                    "writer_policy": field.writer_policy,
                    "required": field.required,
                    "position": field.position,
                    "source_template_id": field.source_template_id,
                    "source_prior_edition_id": field.source_prior_edition_id,
                    "review_status": field.review_status,
                    "status": field.status,
                }
                for field in workspace.profile_fields
            ],
        }
        return Response(
            RegistrationProfileExtensionCatalogSerializer(instance=payload).data
        )

    @extend_schema(
        operation_id="registration_create_profile_extension_field",
        parameters=[_IDEMPOTENCY_PARAMETER, _IDEMPOTENT_REPLAY_RESPONSE_PARAMETER],
        request=RegistrationProfileFieldCreateSerializer,
        responses={
            200: RegistrationDefinitionMutationSerializer,
            201: RegistrationDefinitionMutationSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The header or closed field definition is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Exact-edition catalog authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The selected source is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The version, lifecycle, limit, or retry key conflicts."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "Complete atomic catalog evidence is temporarily unavailable."
            ),
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        actor, series_id = _configuration_manager(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        retry_key = _idempotency_key(request)
        serializer = RegistrationProfileFieldCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = cast(dict[str, Any], serializer.validated_data)
        correlation_id = _request_id(request)
        try:
            result = create_registration_profile_extension_field(
                **_common_command_arguments(
                    actor=actor,
                    organization_id=organization_id,
                    series_id=series_id,
                    edition_id=edition_id,
                    payload=payload,
                    retry_key=retry_key,
                    correlation_id=correlation_id,
                ),
                key=payload["key"],
                label=payload["label"],
                help_text=payload["help_text"],
                field_type=payload["field_type"],
                options=payload["options"],
                purpose=payload["purpose"],
                classification=payload["classification"],
                audience_policy=payload["audience_policy"],
                audience_department_id=payload.get("audience_department_id"),
                writer_policy=payload["writer_policy"],
                required=payload["required"],
                source_template_id=payload.get("source_template_id"),
                source_prior_edition_id=payload.get("source_prior_edition_id"),
                after_field_id=payload.get("after_field_id"),
            )
        except (
            DatabaseError,
            DjangoValidationError,
            RegistrationSetupCommandError,
            RuntimeError,
        ) as error:
            _command_failure(
                request=request,
                operation="profile_field.create",
                error=error,
            )
        return _mutation_response(result, created=True)


@method_decorator(never_cache, name="dispatch")
class RegistrationProfileExtensionFieldCommandView(APIView):
    @extend_schema(
        operation_id="registration_apply_profile_extension_field_command",
        parameters=[_IDEMPOTENCY_PARAMETER, _IDEMPOTENT_REPLAY_RESPONSE_PARAMETER],
        request=_PROFILE_COMMAND_REQUEST,
        responses={
            200: RegistrationDefinitionMutationSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The header, discriminator, or closed command body is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Exact-edition catalog authority is unavailable."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The exact profile field is unavailable."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The version, lifecycle, immutability, or retry key conflicts."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "Complete atomic catalog evidence is temporarily unavailable."
            ),
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        field_id: UUID,
    ) -> Response:
        actor, series_id = _configuration_manager(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        retry_key = _idempotency_key(request)
        operation, payload = _closed_command_payload(
            request,
            serializer_by_operation=PROFILE_COMMAND_SERIALIZER_BY_OPERATION,
        )
        correlation_id = _request_id(request)
        try:
            result = _run_profile_command(
                operation=operation,
                actor=actor,
                organization_id=organization_id,
                series_id=series_id,
                edition_id=edition_id,
                field_id=field_id,
                payload=payload,
                retry_key=retry_key,
                correlation_id=correlation_id,
            )
        except (
            DatabaseError,
            DjangoValidationError,
            RegistrationSetupCommandError,
            RuntimeError,
        ) as error:
            _command_failure(
                request=request,
                operation=operation,
                error=error,
            )
        return _mutation_response(result, created=False)


__all__ = [
    "RegistrationConfigurationCommandView",
    "RegistrationProfileExtensionFieldCollectionView",
    "RegistrationProfileExtensionFieldCommandView",
    "RegistrationSetupStartView",
]
