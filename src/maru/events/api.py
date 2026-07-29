"""Policy-scoped staff API for event editions."""

from typing import cast
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import (
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
from maru.authorization.policy import ResourceScope, decide
from maru.authorization.services import AuthorizationDenied
from maru.core.pagination import StandardPageNumberPagination
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
    EditionListQuerySerializer,
    EditionReadinessGateReviewSerializer,
    EditionReadinessGateSerializer,
    EditionTransitionRequestSerializer,
    EditionTransitionResultSerializer,
)
from maru.events.services import bulk_transition_editions, transition_edition
from maru.identity.models import Account
from maru.identity.services import require_recent_step_up


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
        responses=EditionBasicSerializer(many=True),
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        decision = decide(
            principal=account,
            capability_code="events.view_basic",
            resource=ResourceScope(organization_id=organization_id),
            requested_fields=frozenset(EditionBasicSerializer.Meta.fields),
        )
        if not decision.allowed:
            raise PermissionDenied(
                "You do not have access to this organizer's event editions.",
                code=decision.reason_code,
            )
        _require_api_projection(
            required_fields=frozenset(EditionBasicSerializer.Meta.fields),
            permitted_fields=decision.fields,
        )

        query = EditionListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
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
            raise RuntimeError("Edition list pagination is required.")
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class EditionAutocompleteView(APIView):
    @extend_schema(
        operation_id="events_autocomplete_basic_editions",
        parameters=[EditionAutocompleteQuerySerializer],
        responses=EditionAutocompleteResponseSerializer,
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        required_fields = frozenset(EditionAutocompleteSerializer.Meta.fields)
        decision = decide(
            principal=account,
            capability_code="events.view_basic",
            resource=ResourceScope(organization_id=organization_id),
            requested_fields=required_fields,
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
        query.is_valid(raise_exception=True)
        search = cast(str, query.validated_data["search"])
        limit = cast(int, query.validated_data["limit"])
        editions = (
            EventEdition.objects.filter(organization_id=organization_id)
            .filter(Q(name__icontains=search) | Q(slug__icontains=search))
            .order_by("-starts_on", "name", "id")[:limit]
        )
        serializer = EditionAutocompleteSerializer(editions, many=True)
        return Response({"results": serializer.data})


class EditionBasicDetailView(APIView):
    @extend_schema(
        operation_id="events_retrieve_basic_edition",
        responses=EditionBasicSerializer,
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

        decision = decide(
            principal=account,
            capability_code="events.view_basic",
            resource=ResourceScope(
                organization_id=organization_id,
                edition_id=edition_id,
            ),
            requested_fields=frozenset(EditionBasicSerializer.Meta.fields),
        )
        if not decision.allowed:
            raise PermissionDenied(
                "You do not have access to this event edition.",
                code=decision.reason_code,
            )
        _require_api_projection(
            required_fields=frozenset(EditionBasicSerializer.Meta.fields),
            permitted_fields=decision.fields,
        )

        edition = get_object_or_404(
            EventEdition.objects.filter(
                organization_id=organization_id,
                id=edition_id,
            )
        )
        serializer = EditionBasicSerializer(edition)
        return Response(serializer.data)


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
            resource=ResourceScope(
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
