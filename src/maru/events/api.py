"""Policy-scoped staff API for event editions."""

import logging
from datetime import date
from typing import Any, Never, cast
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    NotFound,
    PermissionDenied,
)
from rest_framework.exceptions import (
    ValidationError as ApiValidationError,
)
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.authorization.enforcement import (
    BulkTargetDeniedError,
    BulkTargetUnavailableError,
    FieldProjectionDeniedError,
    require_complete_projection,
)
from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.core.api_input import reject_unknown_fields
from maru.core.pagination import StandardPageNumberPagination
from maru.core.problems import DependencyUnavailable
from maru.events.closure import (
    closure_counts,
    generate_closure_manifest,
    review_readiness_gate,
)
from maru.events.models import (
    EditionClosureManifest,
    EditionReadinessGate,
    EventEdition,
)
from maru.events.serializers import (
    EditionAutocompleteQuerySerializer,
    EditionAutocompleteResponseSerializer,
    EditionAutocompleteSerializer,
    EditionBasicSerializer,
    EditionBulkTransitionRequestSerializer,
    EditionBulkTransitionResponseSerializer,
    EditionClosureManifestCreateSerializer,
    EditionClosureManifestSerializer,
    EditionCreateRequestSerializer,
    EditionListQuerySerializer,
    EditionProblemSerializer,
    EditionReadinessGateReviewSerializer,
    EditionReadinessGateSerializer,
    EditionTransitionRequestSerializer,
    EditionTransitionResultSerializer,
    EditionUpdateRequestSerializer,
)
from maru.events.services import (
    EventEditionDetails,
    bulk_transition_editions,
    create_event_edition,
    transition_edition,
    update_event_edition,
)
from maru.identity.models import Account
from maru.identity.services import require_recent_step_up
from maru.organizations.models import ConventionSeries, Organization

logger = logging.getLogger(__name__)
PROBLEM_CONTENT_TYPE = "application/problem+json"
EDITION_BASIC_RESPONSE_FIELDS = frozenset(EditionBasicSerializer.Meta.fields)
IDEMPOTENCY_HEADER_NAME = "Idempotency-Key"
MAX_IDEMPOTENCY_HEADER_LENGTH = 64


def _problem_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(response=EditionProblemSerializer, description=description)


def _raise_dependency_unavailable(message: str, error: Exception) -> Never:
    logger.exception(message)
    raise DependencyUnavailable from error


def _raise_idempotency_header_error(*, detail: str, code: str) -> Never:
    raise ApiValidationError(
        cast(
            Any,
            {
                "detail": detail,
                "code": code,
                "errors": {IDEMPOTENCY_HEADER_NAME: [detail]},
            },
        ),
        code=code,
    )


def _edition_idempotency_key(request: Request) -> UUID:
    raw_value = request.headers.get(IDEMPOTENCY_HEADER_NAME)
    if raw_value is None or not raw_value.strip():
        _raise_idempotency_header_error(
            detail="The Idempotency-Key header is required.",
            code="missing_idempotency_key",
        )
    value = raw_value.strip()
    if len(value) > MAX_IDEMPOTENCY_HEADER_LENGTH:
        _raise_idempotency_header_error(
            detail="The Idempotency-Key header must contain one UUID.",
            code="invalid_idempotency_key",
        )
    try:
        return UUID(value)
    except ValueError:
        _raise_idempotency_header_error(
            detail="The Idempotency-Key header must contain one UUID.",
            code="invalid_idempotency_key",
        )


class EditionConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The edition operation conflicts with current state."
    default_code = "edition_conflict"

    def __init__(
        self,
        *,
        detail: dict[str, list[str]] | list[str],
        code: str,
    ) -> None:
        structured_detail: dict[str, object] = {
            "detail": self.default_detail,
            "code": code,
            "errors": detail,
        }
        super().__init__(detail=cast(Any, structured_detail), code=code)


def _django_validation_code(error: DjangoValidationError) -> str:
    if hasattr(error, "error_dict"):
        for field_errors in error.error_dict.values():
            if field_errors:
                return str(field_errors[0].code or "invalid_edition")
    if hasattr(error, "error_list") and error.error_list:
        return str(error.error_list[0].code or "invalid_edition")
    return "invalid_edition"


def _django_validation_detail(
    error: DjangoValidationError,
) -> dict[str, list[str]] | list[str]:
    if hasattr(error, "message_dict"):
        return error.message_dict
    return [str(message) for message in error.messages]


def _require_api_projection(
    *,
    required_fields: frozenset[str],
    permitted_fields: frozenset[str],
) -> None:
    try:
        require_complete_projection(
            required_fields=required_fields,
            permitted_fields=permitted_fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied(
            "The permitted edition projection is incomplete.",
            code="field_projection_denied",
        ) from error


class EditionListView(GenericAPIView[EventEdition]):
    serializer_class = EditionBasicSerializer
    pagination_class = StandardPageNumberPagination

    @extend_schema(
        operation_id="events_list_basic_editions",
        parameters=[EditionListQuerySerializer],
        responses={
            200: EditionBasicSerializer(many=True),
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The list query is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The caller cannot view this organization's editions."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical dependency is temporarily unavailable."
            ),
        },
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        try:
            decision = decide(
                principal=account,
                capability_code="events.view_basic",
                resource=resolve_organization_target(organization_id=organization_id),
                requested_fields=EDITION_BASIC_RESPONSE_FIELDS,
            )
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to authorize the event-edition list",
                error,
            )
        if not decision.allowed:
            raise PermissionDenied(
                "You do not have access to this organizer's event editions.",
                code=decision.reason_code,
            )
        _require_api_projection(
            required_fields=EDITION_BASIC_RESPONSE_FIELDS,
            permitted_fields=decision.fields,
        )

        query = EditionListQuerySerializer(data=request.query_params)
        reject_unknown_fields(
            request.query_params,
            allowed_fields=frozenset(query.fields),
        )
        query.is_valid(raise_exception=True)
        values = query.validated_data
        try:
            editions = EventEdition.objects.filter(organization_id=organization_id)
            if lifecycle := values.get("lifecycle"):
                editions = editions.filter(lifecycle=lifecycle)
            if search := values.get("search"):
                editions = editions.filter(
                    Q(name__icontains=search) | Q(slug__icontains=search)
                )
            editions = editions.order_by("-starts_on", "name", "id")
            page = self.paginate_queryset(editions)
            if page is None:
                raise RuntimeError(  # noqa: TRY301
                    "Edition list pagination is required."
                )
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to load the event-edition list",
                error,
            )

    @extend_schema(
        operation_id="events_create_edition",
        request=EditionCreateRequestSerializer,
        parameters=[
            OpenApiParameter(
                name=IDEMPOTENCY_HEADER_NAME,
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.HEADER,
                required=True,
                description=(
                    "Caller-generated UUID reused only when retrying this exact "
                    "edition-creation command."
                ),
            )
        ],
        responses={
            200: EditionBasicSerializer,
            201: EditionBasicSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The idempotency header or complete edition profile is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The caller cannot create an edition in this organization."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The scoped organization or convention series does not exist."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The request conflicts with current parent or idempotency state."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical dependency is temporarily unavailable."
            ),
        },
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        try:
            decision = decide(
                principal=account,
                capability_code="events.create",
                resource=resolve_organization_target(organization_id=organization_id),
                requested_fields=EDITION_BASIC_RESPONSE_FIELDS,
            )
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to authorize event-edition creation",
                error,
            )
        if not decision.allowed:
            raise PermissionDenied(
                "You do not have access to create event editions.",
                code=decision.reason_code,
            )
        _require_api_projection(
            required_fields=EDITION_BASIC_RESPONSE_FIELDS,
            permitted_fields=decision.fields,
        )
        idempotency_key = _edition_idempotency_key(request)
        reject_unknown_fields(
            request.data,
            allowed_fields=frozenset(EditionCreateRequestSerializer().fields),
        )
        serializer = EditionCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        try:
            result = create_event_edition(
                actor=account,
                organization_id=organization_id,
                series_id=cast(UUID, values["series_id"]),
                details=EventEditionDetails(
                    name=cast(str, values["name"]),
                    starts_on=cast(date, values["starts_on"]),
                    ends_on=cast(date, values["ends_on"]),
                    time_zone=cast(str, values["time_zone"]),
                    language_codes=tuple(cast(list[str], values["language_codes"])),
                    currency_codes=tuple(cast(list[str], values["currency_codes"])),
                ),
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(str(error), code=error.reason_code) from error
        except (Organization.DoesNotExist, ConventionSeries.DoesNotExist) as error:
            raise NotFound(
                "The scoped organization or convention series does not exist.",
                code="edition_parent_not_found",
            ) from error
        except DjangoValidationError as error:
            code = _django_validation_code(error)
            if code in {
                "edition_creation_idempotency_conflict",
                "edition_parent_closed",
                "edition_series_inactive",
            }:
                raise EditionConflict(
                    detail=_django_validation_detail(error),
                    code=code,
                ) from error
            raise ApiValidationError(
                _django_validation_detail(error),
                code=code,
            ) from error
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to create the event edition",
                error,
            )
        response_status = (
            status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED
        )
        return Response(
            EditionBasicSerializer(result.edition).data,
            status=response_status,
        )


class EditionAutocompleteView(APIView):
    @extend_schema(
        operation_id="events_autocomplete_basic_editions",
        parameters=[EditionAutocompleteQuerySerializer],
        responses={
            200: EditionAutocompleteResponseSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The autocomplete query is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The caller cannot view this organization's edition suggestions."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical dependency is temporarily unavailable."
            ),
        },
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        required_fields = frozenset(EditionAutocompleteSerializer.Meta.fields)
        try:
            decision = decide(
                principal=account,
                capability_code="events.view_basic",
                resource=resolve_organization_target(organization_id=organization_id),
                requested_fields=required_fields,
            )
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to authorize event-edition suggestions",
                error,
            )
        if not decision.allowed:
            raise PermissionDenied(
                "You do not have access to this organizer's edition suggestions.",
                code=decision.reason_code,
            )
        _require_api_projection(
            required_fields=required_fields,
            permitted_fields=decision.fields,
        )

        query = EditionAutocompleteQuerySerializer(data=request.query_params)
        reject_unknown_fields(
            request.query_params,
            allowed_fields=frozenset(query.fields),
        )
        query.is_valid(raise_exception=True)
        search = cast(str, query.validated_data["search"])
        limit = cast(int, query.validated_data["limit"])
        try:
            editions = (
                EventEdition.objects.filter(organization_id=organization_id)
                .filter(Q(name__icontains=search) | Q(slug__icontains=search))
                .order_by("-starts_on", "name", "id")[:limit]
            )
            serializer = EditionAutocompleteSerializer(editions, many=True)
            return Response({"results": serializer.data})
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to load event-edition suggestions",
                error,
            )


class EditionBasicDetailView(APIView):
    @extend_schema(
        operation_id="events_retrieve_basic_edition",
        responses={
            200: EditionBasicSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The detail query is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The caller cannot view this event edition."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The scoped event edition does not exist."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical dependency is temporarily unavailable."
            ),
        },
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")

        try:
            decision = decide(
                principal=account,
                capability_code="events.view_basic",
                resource=resolve_edition_target(
                    organization_id=organization_id,
                    edition_id=edition_id,
                ),
                requested_fields=EDITION_BASIC_RESPONSE_FIELDS,
            )
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to authorize the event-edition record",
                error,
            )
        if not decision.allowed:
            raise PermissionDenied(
                "You do not have access to this event edition.",
                code=decision.reason_code,
            )
        _require_api_projection(
            required_fields=EDITION_BASIC_RESPONSE_FIELDS,
            permitted_fields=decision.fields,
        )
        reject_unknown_fields(
            request.query_params,
            allowed_fields=frozenset(),
        )

        try:
            edition = get_object_or_404(
                EventEdition.objects.filter(
                    organization_id=organization_id,
                    id=edition_id,
                )
            )
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to load the event-edition record",
                error,
            )
        serializer = EditionBasicSerializer(edition)
        return Response(serializer.data)

    @extend_schema(
        operation_id="events_update_edition",
        request=EditionUpdateRequestSerializer,
        responses={
            200: EditionBasicSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The complete edition profile is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "The caller cannot change this edition profile."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The scoped event edition does not exist."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The edition is read-only or its aggregate version is stale."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical dependency is temporarily unavailable."
            ),
        },
    )
    def put(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")

        try:
            decision = decide(
                principal=account,
                capability_code="events.change_profile",
                resource=resolve_edition_target(
                    organization_id=organization_id,
                    edition_id=edition_id,
                ),
                requested_fields=EDITION_BASIC_RESPONSE_FIELDS,
            )
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to authorize the event-edition profile update",
                error,
            )
        if not decision.allowed:
            raise PermissionDenied(
                "You do not have access to change this event edition.",
                code=decision.reason_code,
            )
        _require_api_projection(
            required_fields=EDITION_BASIC_RESPONSE_FIELDS,
            permitted_fields=decision.fields,
        )
        try:
            edition = get_object_or_404(
                EventEdition.objects.only("id", "series_id").filter(
                    organization_id=organization_id,
                    id=edition_id,
                )
            )
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to resolve the event edition for profile update",
                error,
            )
        reject_unknown_fields(
            request.data,
            allowed_fields=frozenset(EditionUpdateRequestSerializer().fields),
        )
        serializer = EditionUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        try:
            result = update_event_edition(
                actor=account,
                organization_id=organization_id,
                series_id=edition.series_id,
                edition_id=edition_id,
                expected_aggregate_version=cast(
                    int,
                    values["expected_aggregate_version"],
                ),
                details=EventEditionDetails(
                    name=cast(str, values["name"]),
                    starts_on=cast(date, values["starts_on"]),
                    ends_on=cast(date, values["ends_on"]),
                    time_zone=cast(str, values["time_zone"]),
                    language_codes=tuple(cast(list[str], values["language_codes"])),
                    currency_codes=tuple(cast(list[str], values["currency_codes"])),
                ),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(str(error), code=error.reason_code) from error
        except (
            Organization.DoesNotExist,
            ConventionSeries.DoesNotExist,
            EventEdition.DoesNotExist,
        ) as error:
            raise NotFound(
                "The scoped event edition does not exist.",
                code="edition_not_found",
            ) from error
        except DjangoValidationError as error:
            code = _django_validation_code(error)
            if code in {
                "edition_parent_closed",
                "edition_profile_read_only",
                "stale_edition_version",
            }:
                raise EditionConflict(
                    detail=_django_validation_detail(error),
                    code=code,
                ) from error
            raise ApiValidationError(
                _django_validation_detail(error),
                code=code,
            ) from error
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to update the event-edition profile",
                error,
            )
        return Response(EditionBasicSerializer(result.edition).data)


class EditionTransitionView(APIView):
    @extend_schema(
        operation_id="events_transition_edition",
        request=EditionTransitionRequestSerializer,
        responses=EditionTransitionResultSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        serializer = EditionTransitionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        try:
            edition = transition_edition(
                organization_id=organization_id,
                edition_id=edition_id,
                to_state=serializer.validated_data["to_state"],
                actor=account,
                reason=serializer.validated_data["reason"],
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                str(error),
                code=error.reason_code,
            ) from error
        except EventEdition.DoesNotExist as error:
            raise NotFound(
                "The event edition does not exist.",
                code="edition_not_found",
            ) from error
        return Response(EditionTransitionResultSerializer(edition).data)


class EditionBulkTransitionView(APIView):
    @extend_schema(
        operation_id="events_bulk_transition_editions",
        request=EditionBulkTransitionRequestSerializer,
        responses=EditionBulkTransitionResponseSerializer,
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        serializer = EditionBulkTransitionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        try:
            editions = bulk_transition_editions(
                organization_id=organization_id,
                edition_ids=tuple(cast(list[UUID], values["edition_ids"])),
                to_state=cast(str, values["to_state"]),
                actor=account,
                reason=cast(str, values["reason"]),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
            )
        except (
            BulkTargetDeniedError,
            BulkTargetUnavailableError,
            AuthorizationDenied,
        ) as error:
            raise NotFound(
                "One or more edition targets are unavailable.",
                code="bulk_target_unavailable",
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "One or more editions cannot make that transition.",
                    "code": "invalid_transition",
                }
            ) from error
        result = EditionTransitionResultSerializer(editions, many=True)
        return Response({"results": result.data})


class EditionClosureReadinessView(APIView):
    @extend_schema(operation_id="events_get_closure_readiness", responses=dict)
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        decision = decide(
            principal=account,
            capability_code="events.transition",
            resource=resolve_edition_target(
                organization_id=organization_id,
                edition_id=edition_id,
            ),
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Edition closure readiness is unavailable.",
                code=decision.reason_code,
            )
        edition = get_object_or_404(
            EventEdition,
            id=edition_id,
            organization_id=organization_id,
        )
        gates = EditionReadinessGate.objects.filter(edition=edition)
        manifest = EditionClosureManifest.objects.filter(edition=edition).first()
        return Response(
            {
                "counts": closure_counts(
                    organization_id=organization_id,
                    edition_id=edition_id,
                ),
                "gates": EditionReadinessGateSerializer(gates, many=True).data,
                "manifest": (
                    EditionClosureManifestSerializer(manifest).data
                    if manifest
                    else None
                ),
            }
        )


class EditionReadinessGateReviewView(APIView):
    @extend_schema(
        operation_id="events_review_closure_gate",
        request=EditionReadinessGateReviewSerializer,
        responses=EditionReadinessGateSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        code: str,
    ) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        serializer = EditionReadinessGateReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            if settings.REQUIRE_PRIVILEGED_STEP_UP:
                require_recent_step_up(account=account, request=request._request)
            gate = review_readiness_gate(
                actor=account,
                organization_id=organization_id,
                edition_id=edition_id,
                code=code,
                approve=values["approve"],
                evidence_reference=values["evidence_reference"],
                summary=values["summary"],
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Edition closure readiness is unavailable.",
                code=error.reason_code,
            ) from error
        except EventEdition.DoesNotExist as error:
            raise NotFound("The event edition is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {"detail": "The gate could not be reviewed.", "code": error.code}
            ) from error
        return Response(EditionReadinessGateSerializer(gate).data)


class EditionClosureManifestCreateView(APIView):
    @extend_schema(
        operation_id="events_generate_closure_manifest",
        request=EditionClosureManifestCreateSerializer,
        responses={201: EditionClosureManifestSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        serializer = EditionClosureManifestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        edition = get_object_or_404(
            EventEdition,
            id=edition_id,
            organization_id=organization_id,
        )
        try:
            if settings.REQUIRE_PRIVILEGED_STEP_UP:
                require_recent_step_up(account=account, request=request._request)
            manifest = generate_closure_manifest(
                edition=edition,
                actor=account,
                recovery_reference=serializer.validated_data["recovery_reference"],
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Edition closure is unavailable.",
                code=error.reason_code,
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The closure manifest could not be generated.",
                    "code": error.code,
                }
            ) from error
        return Response(EditionClosureManifestSerializer(manifest).data, status=201)
