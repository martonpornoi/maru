"""Strict versioned API boundaries for venue and space scheduling."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Never, cast
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.core.api_input import reject_unknown_fields
from maru.core.problems import DependencyUnavailable
from maru.identity.models import Account

from .authorization import resolve_edition_space_target
from .queries import (
    authorize_my_maru_schedule_scope,
    list_venue_properties,
    list_venue_workspace,
    load_space_schedule,
    my_maru_schedule_for_edition,
    public_schedule_for_edition,
)
from .serializers import (
    PublicVenueScheduleItemSerializer,
    VenueAvailabilitySetSerializer,
    VenueBookingCreateSerializer,
    VenueBookingStateSerializer,
    VenueBookingUpdateSerializer,
    VenueCombinationCreateSerializer,
    VenueCommandResultSerializer,
    VenueLayoutAddSerializer,
    VenueLayoutApproveSerializer,
    VenueMediaAddSerializer,
    VenueMediaApproveSerializer,
    VenueNightInventorySetSerializer,
    VenuePropertyCreateSerializer,
    VenuePropertySummarySerializer,
    VenuePropertyUpdateSerializer,
    VenueRoomTypeCreateSerializer,
    VenueSelectionCreateSerializer,
    VenueSpaceCatalogCreateSerializer,
    VenueSpaceScheduleSerializer,
    VenueSpaceSelectionCreateSerializer,
    VenueWorkspaceSpaceSerializer,
)
from .services import (
    EDITION_SELECT_CAPABILITY,
    PROPERTY_MANAGE_CAPABILITY,
    PROPERTY_VIEW_CAPABILITY,
    SPACE_MANAGE_CAPABILITY,
    SPACE_PUBLISH_CAPABILITY,
    SPACE_VIEW_CAPABILITY,
    WORKSPACE_VIEW_CAPABILITY,
    VenueAuthorizationDeniedError,
    VenueAvailabilityConflictError,
    VenueAvailabilityInterval,
    VenueBookingEnvelope,
    VenueBookingOverlapError,
    VenueCapacityConflictError,
    VenueCapacityProfile,
    VenueCommandError,
    VenueIndependentApprovalError,
    VenuePropertyProfile,
    VenueResourceUnavailableError,
    VenueRetryConflictError,
    VenueSpaceCatalogInput,
    VenueStateConflictError,
    VenueVersionConflictError,
    add_venue_layout_version,
    add_venue_property_media,
    approve_venue_booking,
    approve_venue_layout_version,
    approve_venue_property_media,
    cancel_venue_booking,
    create_accommodation_room_type,
    create_venue_booking,
    create_venue_property,
    create_venue_space_catalog_path,
    create_venue_space_combination,
    publish_venue_booking,
    reschedule_venue_booking,
    select_space_for_edition,
    select_venue_for_edition,
    set_accommodation_night_inventory,
    set_edition_space_availability,
    update_venue_property,
    withdraw_venue_booking_publication,
)

IDEMPOTENCY_HEADER = "Idempotency-Key"
MAX_IDEMPOTENCY_HEADER_LENGTH = 64
CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)
_IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name=IDEMPOTENCY_HEADER,
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    pattern=CANONICAL_UUID_PATTERN,
    description=(
        "Canonical lower-case hyphenated UUID. Exact creation retries return "
        "HTTP 200; newly created resources return HTTP 201."
    ),
)
_BOOKING_ACTION_PARAMETER = OpenApiParameter(
    name="action",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    required=True,
    enum=("approve", "publish", "withdraw", "cancel"),
)


class _CompleteBookingPatchSchema(AutoSchema):
    """Describe the reschedule PATCH as the complete replacement it accepts."""

    def _get_request_for_media_type(
        self, serializer: Any, direction: str = "request"
    ) -> tuple[dict[str, Any] | None, bool]:
        original_method = self.method
        try:
            self.method = "PUT"
            return cast(
                tuple[dict[str, Any] | None, bool],
                super()._get_request_for_media_type(  # type: ignore[no-untyped-call]
                    serializer, direction
                ),
            )
        finally:
            self.method = original_method


class VenueConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The venue operation conflicts with current state."
    default_code = "venue_conflict"

    def __init__(self, *, code: str) -> None:
        super().__init__(
            detail=cast(Any, {"detail": self.default_detail, "code": code}),
            code=code,
        )


def _account(request: Request) -> Account:
    account = request.user
    if not isinstance(account, Account) or not account.is_active:
        raise PermissionDenied(
            "The requested venue workspace is unavailable.",
            code=VenueAuthorizationDeniedError.reason_code,
        )
    return account


def _deny() -> Never:
    raise PermissionDenied(
        "The requested venue workspace is unavailable.",
        code=VenueAuthorizationDeniedError.reason_code,
    )


def _authorize_organization(
    request: Request, *, organization_id: UUID, capability_code: str
) -> Account:
    account = _account(request)
    if not decide(
        principal=account,
        capability_code=capability_code,
        resource=resolve_organization_target(organization_id=organization_id),
    ).allowed:
        _deny()
    return account


def _authorize_edition(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
) -> Account:
    account = _account(request)
    if not decide(
        principal=account,
        capability_code=capability_code,
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    ).allowed:
        _deny()
    return account


def _authorize_space(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
    capability_code: str,
) -> Account:
    account = _account(request)
    target = resolve_edition_space_target(
        organization_id=organization_id,
        edition_id=edition_id,
        space_selection_id=space_selection_id,
    )
    if not decide(
        principal=account,
        capability_code=capability_code,
        resource=target,
    ).allowed:
        _deny()
    return account


def _idempotency_key(request: Request) -> UUID:
    raw_value = request.headers.get(IDEMPOTENCY_HEADER)
    if (
        raw_value is None
        or not raw_value.strip()
        or len(raw_value) > MAX_IDEMPOTENCY_HEADER_LENGTH
    ):
        raise ApiValidationError(
            {IDEMPOTENCY_HEADER: ["Provide one canonical UUID."]},
            code="invalid_idempotency_key",
        )
    try:
        value = UUID(raw_value)
    except ValueError as error:
        raise ApiValidationError(
            {IDEMPOTENCY_HEADER: ["Provide one canonical UUID."]},
            code="invalid_idempotency_key",
        ) from error
    if str(value) != raw_value:
        raise ApiValidationError(
            {IDEMPOTENCY_HEADER: ["Provide one canonical UUID."]},
            code="invalid_idempotency_key",
        )
    return value


def _correlation_id(request: Request) -> UUID:
    value = getattr(request, "correlation_id", None)
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return uuid4()


def _validated[Payload: dict[str, object]](
    request: Request,
    serializer_class: type[serializers.Serializer[Payload]],
) -> Payload:
    reject_unknown_fields(request.query_params, allowed_fields=frozenset())
    serializer = serializer_class(data=request.data)
    reject_unknown_fields(request.data, allowed_fields=frozenset(serializer.fields))
    serializer.is_valid(raise_exception=True)
    return cast(Payload, serializer.validated_data)


def _django_validation(error: DjangoValidationError) -> Never:
    if hasattr(error, "message_dict"):
        raise ApiValidationError(error.message_dict) from error
    raise ApiValidationError(
        {"non_field_errors": ["The venue input is invalid."]},
        code="venue_input_invalid",
    ) from error


def _execute[Result](command: Callable[[], Result]) -> Result:
    try:
        return command()
    except VenueAuthorizationDeniedError:
        _deny()
    except VenueResourceUnavailableError as error:
        raise NotFound(
            "The requested venue record is unavailable.",
            code=error.reason_code,
        ) from error
    except (
        VenueVersionConflictError,
        VenueRetryConflictError,
        VenueStateConflictError,
        VenueIndependentApprovalError,
        VenueAvailabilityConflictError,
        VenueCapacityConflictError,
        VenueBookingOverlapError,
    ) as error:
        raise VenueConflict(code=error.reason_code) from error
    except DjangoValidationError as error:
        _django_validation(error)
    except IntegrityError as error:
        raise VenueConflict(code=VenueStateConflictError.reason_code) from error
    except (DatabaseError, VenueCommandError) as error:
        raise DependencyUnavailable from error


def _result_response(result: Any, *, created: bool = False) -> Response:
    payload = VenueCommandResultSerializer(asdict(result)).data
    response_status = (
        status.HTTP_201_CREATED
        if created and not result.replayed
        else status.HTTP_200_OK
    )
    return Response(payload, status=response_status)


def _booking_envelope(values: dict[str, object]) -> VenueBookingEnvelope:
    return VenueBookingEnvelope(
        setup_starts_at=cast(Any, values["setup_starts_at"]),
        effective_starts_at=cast(Any, values["effective_starts_at"]),
        effective_ends_at=cast(Any, values["effective_ends_at"]),
        teardown_ends_at=cast(Any, values["teardown_ends_at"]),
    )


class PublicVenueScheduleView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="venues_list_public_schedule",
        responses={200: PublicVenueScheduleItemSerializer(many=True)},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = public_schedule_for_edition(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        return Response(
            PublicVenueScheduleItemSerializer(cast(Any, projection), many=True).data
        )


@method_decorator(never_cache, name="dispatch")
class PrivateVenueAPIView(APIView):
    """Authenticated venue response boundary, including safe error responses."""


class MyMaruVenueScheduleView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_list_my_schedule",
        responses={200: PublicVenueScheduleItemSerializer(many=True)},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _account(request)
        _execute(
            lambda: authorize_my_maru_schedule_scope(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = _execute(
            lambda: my_maru_schedule_for_edition(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        return Response(
            PublicVenueScheduleItemSerializer(cast(Any, projection), many=True).data
        )


class VenuePropertyCollectionView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_list_properties",
        responses={200: VenuePropertySummarySerializer(many=True)},
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PROPERTY_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = list_venue_properties(
            actor=actor,
            organization_id=organization_id,
            purpose="venue_property_api_directory",
            correlation_id=_correlation_id(request),
            source_channel="api",
        )
        return Response(
            VenuePropertySummarySerializer(cast(Any, projection), many=True).data
        )

    @extend_schema(
        operation_id="venues_create_property",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenuePropertyCreateSerializer,
        responses={
            200: VenueCommandResultSerializer,
            201: VenueCommandResultSerializer,
        },
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PROPERTY_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenuePropertyCreateSerializer)
        profile = VenuePropertyProfile(
            **{
                field_name: str(values.get(field_name, ""))
                for field_name in VenuePropertyProfile.__dataclass_fields__
            }
        )
        result = _execute(
            lambda: create_venue_property(
                actor=actor,
                organization_id=organization_id,
                slug=str(values["slug"]),
                profile=profile,
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class VenuePropertyDetailView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_update_property",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenuePropertyUpdateSerializer,
        responses={200: VenueCommandResultSerializer},
    )
    def patch(
        self, request: Request, organization_id: UUID, property_id: UUID
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PROPERTY_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenuePropertyUpdateSerializer)
        changes = {
            key: str(value)
            for key, value in values.items()
            if key not in {"expected_version", "reason"}
        }
        result = _execute(
            lambda: update_venue_property(
                actor=actor,
                organization_id=organization_id,
                property_id=property_id,
                expected_version=cast(int, values["expected_version"]),
                changes=changes,
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class VenueSpaceCatalogCollectionView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_create_space_path",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueSpaceCatalogCreateSerializer,
        responses={
            200: VenueCommandResultSerializer,
            201: VenueCommandResultSerializer,
        },
    )
    def post(
        self, request: Request, organization_id: UUID, property_id: UUID
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PROPERTY_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenueSpaceCatalogCreateSerializer)
        catalog = VenueSpaceCatalogInput(
            site_code=str(values["site_code"]),
            site_name=str(values["site_name"]),
            building_code=str(values["building_code"]),
            building_name=str(values["building_name"]),
            space_code=str(values["space_code"]),
            space_name=str(values["space_name"]),
            space_kind=str(values["space_kind"]),
            configuration_code=str(values["configuration_code"]),
            configuration_name=str(values["configuration_name"]),
            seated_capacity=cast(int, values["seated_capacity"]),
            standing_capacity=cast(int, values["standing_capacity"]),
            table_capacity=cast(int, values["table_capacity"]),
            fire_capacity=cast(int, values["fire_capacity"]),
            public_description=str(values.get("public_description", "")),
            accessibility_features=str(values.get("accessibility_features", "")),
            known_barriers=str(values.get("known_barriers", "")),
            equipment_facts=str(values.get("equipment_facts", "")),
        )
        result = _execute(
            lambda: create_venue_space_catalog_path(
                actor=actor,
                organization_id=organization_id,
                property_id=property_id,
                catalog=catalog,
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class VenueCombinationCollectionView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_create_space_combination",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueCombinationCreateSerializer,
        responses={
            200: VenueCommandResultSerializer,
            201: VenueCommandResultSerializer,
        },
    )
    def post(
        self, request: Request, organization_id: UUID, property_id: UUID
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PROPERTY_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenueCombinationCreateSerializer)
        result = _execute(
            lambda: create_venue_space_combination(
                actor=actor,
                organization_id=organization_id,
                property_id=property_id,
                code=str(values["code"]),
                name=str(values["name"]),
                member_space_ids=cast(list[UUID], values["member_space_ids"]),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class VenueMediaCollectionView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_add_property_media",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueMediaAddSerializer,
        responses={
            200: VenueCommandResultSerializer,
            201: VenueCommandResultSerializer,
        },
    )
    def post(
        self, request: Request, organization_id: UUID, property_id: UUID
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PROPERTY_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenueMediaAddSerializer)
        result = _execute(
            lambda: add_venue_property_media(
                actor=actor,
                organization_id=organization_id,
                property_id=property_id,
                kind=str(values["kind"]),
                source_reference=str(values["source_reference"]),
                owner_name=str(values["owner_name"]),
                license_basis=str(values["license_basis"]),
                usage_scope=str(values["usage_scope"]),
                attribution=str(values.get("attribution", "")),
                expires_at=cast(Any, values.get("expires_at")),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class VenueMediaApproveView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_approve_property_media",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueMediaApproveSerializer,
        responses={200: VenueCommandResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        property_id: UUID,
        media_id: UUID,
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PROPERTY_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenueMediaApproveSerializer)
        result = _execute(
            lambda: approve_venue_property_media(
                actor=actor,
                organization_id=organization_id,
                property_id=property_id,
                media_id=media_id,
                expected_version=cast(int, values["expected_version"]),
                public_reference=str(values["public_reference"]),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class VenueLayoutCollectionView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_add_space_layout",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueLayoutAddSerializer,
        responses={
            200: VenueCommandResultSerializer,
            201: VenueCommandResultSerializer,
        },
    )
    def post(self, request: Request, organization_id: UUID, space_id: UUID) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PROPERTY_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenueLayoutAddSerializer)
        result = _execute(
            lambda: add_venue_layout_version(
                actor=actor,
                organization_id=organization_id,
                space_id=space_id,
                layout_code=str(values["layout_code"]),
                version=cast(int, values["version"]),
                title=str(values["title"]),
                visibility=str(values["visibility"]),
                source_reference=str(values["source_reference"]),
                checksum_sha256=str(values["checksum_sha256"]),
                notes=str(values.get("notes", "")),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class VenueLayoutApproveView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_approve_space_layout",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueLayoutApproveSerializer,
        responses={200: VenueCommandResultSerializer},
    )
    def post(
        self, request: Request, organization_id: UUID, layout_id: UUID
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PROPERTY_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenueLayoutApproveSerializer)
        result = _execute(
            lambda: approve_venue_layout_version(
                actor=actor,
                organization_id=organization_id,
                layout_id=layout_id,
                expected_version=cast(int, values["expected_version"]),
                approved_reference=str(values.get("approved_reference", "")),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class VenueRoomTypeCollectionView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_create_accommodation_room_type",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueRoomTypeCreateSerializer,
        responses={
            200: VenueCommandResultSerializer,
            201: VenueCommandResultSerializer,
        },
    )
    def post(
        self, request: Request, organization_id: UUID, property_id: UUID
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code="venues.manage_accommodation",
        )
        values = _validated(request, VenueRoomTypeCreateSerializer)
        result = _execute(
            lambda: create_accommodation_room_type(
                actor=actor,
                organization_id=organization_id,
                property_id=property_id,
                code=str(values["code"]),
                public_name=str(values["public_name"]),
                description=str(values.get("description", "")),
                accessible_features=str(values.get("accessible_features", "")),
                minimum_occupants=cast(int, values["minimum_occupants"]),
                maximum_occupants=cast(int, values["maximum_occupants"]),
                provider_reference=str(values.get("provider_reference", "")),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class VenueNightInventoryView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_set_accommodation_night_inventory",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueNightInventorySetSerializer,
        responses={200: VenueCommandResultSerializer},
    )
    def put(
        self, request: Request, organization_id: UUID, room_type_id: UUID
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code="venues.manage_accommodation",
        )
        values = _validated(request, VenueNightInventorySetSerializer)
        result = _execute(
            lambda: set_accommodation_night_inventory(
                actor=actor,
                organization_id=organization_id,
                room_type_id=room_type_id,
                night=cast(Any, values["night"]),
                room_capacity=cast(int, values["room_capacity"]),
                release_at=cast(Any, values["release_at"]),
                provider_reference=str(values.get("provider_reference", "")),
                expected_version=cast(int | None, values.get("expected_version")),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class VenueWorkspaceCollectionView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_list_edition_workspace",
        responses={200: VenueWorkspaceSpaceSerializer(many=True)},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _authorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=WORKSPACE_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = list_venue_workspace(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        return Response(
            VenueWorkspaceSpaceSerializer(cast(Any, projection), many=True).data
        )

    @extend_schema(
        operation_id="venues_select_property_for_edition",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueSelectionCreateSerializer,
        responses={
            200: VenueCommandResultSerializer,
            201: VenueCommandResultSerializer,
        },
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _authorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=EDITION_SELECT_CAPABILITY,
        )
        values = _validated(request, VenueSelectionCreateSerializer)
        result = _execute(
            lambda: select_venue_for_edition(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                property_id=cast(UUID, values["property_id"]),
                responsible_department_id=cast(
                    UUID, values["responsible_department_id"]
                ),
                local_name=str(values["local_name"]),
                public_description_override=str(
                    values.get("public_description_override", "")
                ),
                public_contact_override=str(values.get("public_contact_override", "")),
                opening_restrictions=str(values.get("opening_restrictions", "")),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class VenueSpaceSelectionCollectionView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_select_space_for_edition",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueSpaceSelectionCreateSerializer,
        responses={
            200: VenueCommandResultSerializer,
            201: VenueCommandResultSerializer,
        },
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _authorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=EDITION_SELECT_CAPABILITY,
        )
        values = _validated(request, VenueSpaceSelectionCreateSerializer)
        raw_capacity = cast(dict[str, object] | None, values.get("capacity"))
        capacity = (
            VenueCapacityProfile(
                configuration_name=str(raw_capacity["configuration_name"]),
                seated_capacity=cast(int, raw_capacity["seated_capacity"]),
                standing_capacity=cast(int, raw_capacity["standing_capacity"]),
                table_capacity=cast(int, raw_capacity["table_capacity"]),
                fire_capacity=cast(int, raw_capacity["fire_capacity"]),
            )
            if raw_capacity is not None
            else None
        )
        result = _execute(
            lambda: select_space_for_edition(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                venue_selection_id=cast(UUID, values["venue_selection_id"]),
                source_space_id=cast(UUID | None, values.get("source_space_id")),
                source_combination_id=cast(
                    UUID | None, values.get("source_combination_id")
                ),
                selected_configuration_id=cast(
                    UUID | None, values.get("selected_configuration_id")
                ),
                local_name=str(values["local_name"]),
                capacity=capacity,
                public_access_info=str(values.get("public_access_info", "")),
                opening_restrictions=str(values.get("opening_restrictions", "")),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class VenueSpaceScheduleView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_retrieve_space_schedule",
        responses={200: VenueSpaceScheduleSerializer},
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        space_selection_id: UUID,
    ) -> Response:
        actor = _authorize_space(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id=space_selection_id,
            capability_code=SPACE_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = load_space_schedule(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id=space_selection_id,
            purpose="venue_space_schedule_api",
            correlation_id=_correlation_id(request),
            source_channel="api",
        )
        return Response(VenueSpaceScheduleSerializer(cast(Any, projection)).data)


class VenueSpaceAvailabilityView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_set_space_availability",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueAvailabilitySetSerializer,
        responses={200: VenueCommandResultSerializer},
    )
    def put(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        space_selection_id: UUID,
    ) -> Response:
        actor = _authorize_space(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id=space_selection_id,
            capability_code=SPACE_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenueAvailabilitySetSerializer)
        intervals = tuple(
            VenueAvailabilityInterval(
                starts_at=cast(Any, row["starts_at"]),
                ends_at=cast(Any, row["ends_at"]),
                opening_restriction=str(row.get("opening_restriction", "")),
            )
            for row in cast(list[dict[str, object]], values["intervals"])
        )
        result = _execute(
            lambda: set_edition_space_availability(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                space_selection_id=space_selection_id,
                expected_version=cast(int, values["expected_version"]),
                intervals=intervals,
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class VenueBookingCollectionView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_create_booking",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueBookingCreateSerializer,
        responses={
            200: VenueCommandResultSerializer,
            201: VenueCommandResultSerializer,
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        space_selection_id: UUID,
    ) -> Response:
        actor = _authorize_space(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id=space_selection_id,
            capability_code=SPACE_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenueBookingCreateSerializer)
        result = _execute(
            lambda: create_venue_booking(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                space_selection_id=space_selection_id,
                kind=str(values["kind"]),
                external_reference=str(values.get("external_reference", "")),
                internal_title=str(values["internal_title"]),
                public_title=str(values.get("public_title", "")),
                public_description=str(values.get("public_description", "")),
                capacity_mode=str(values["capacity_mode"]),
                expected_attendance=cast(int, values["expected_attendance"]),
                envelope=_booking_envelope(values),
                public_layout_id=cast(UUID | None, values.get("public_layout_id")),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class VenueBookingDetailView(PrivateVenueAPIView):
    schema = _CompleteBookingPatchSchema()

    @extend_schema(
        operation_id="venues_reschedule_booking",
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VenueBookingUpdateSerializer,
        responses={200: VenueCommandResultSerializer},
    )
    def patch(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        space_selection_id: UUID,
        booking_id: UUID,
    ) -> Response:
        actor = _authorize_space(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id=space_selection_id,
            capability_code=SPACE_MANAGE_CAPABILITY,
        )
        values = _validated(request, VenueBookingUpdateSerializer)
        result = _execute(
            lambda: reschedule_venue_booking(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                space_selection_id=space_selection_id,
                booking_id=booking_id,
                expected_version=cast(int, values["expected_version"]),
                kind=str(values["kind"]),
                external_reference=str(values.get("external_reference", "")),
                internal_title=str(values["internal_title"]),
                public_title=str(values.get("public_title", "")),
                public_description=str(values.get("public_description", "")),
                capacity_mode=str(values["capacity_mode"]),
                expected_attendance=cast(int, values["expected_attendance"]),
                envelope=_booking_envelope(values),
                public_layout_id=cast(UUID | None, values.get("public_layout_id")),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class VenueBookingCommandView(PrivateVenueAPIView):
    @extend_schema(
        operation_id="venues_apply_booking_command",
        parameters=[_IDEMPOTENCY_PARAMETER, _BOOKING_ACTION_PARAMETER],
        request=VenueBookingStateSerializer,
        responses={200: VenueCommandResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        space_selection_id: UUID,
        booking_id: UUID,
        action: str,
    ) -> Response:
        capability = (
            SPACE_PUBLISH_CAPABILITY
            if action in {"publish", "withdraw"}
            else SPACE_MANAGE_CAPABILITY
        )
        actor = _authorize_space(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id=space_selection_id,
            capability_code=capability,
        )
        commands = {
            "approve": approve_venue_booking,
            "publish": publish_venue_booking,
            "withdraw": withdraw_venue_booking_publication,
            "cancel": cancel_venue_booking,
        }
        command = commands.get(action)
        if command is None:
            raise NotFound("The requested venue operation is unavailable.")
        values = _validated(request, VenueBookingStateSerializer)
        result = _execute(
            lambda: command(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                space_selection_id=space_selection_id,
                booking_id=booking_id,
                expected_version=cast(int, values["expected_version"]),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)
