"""Strict authenticated API boundary for logistics offers and operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Never, cast
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.core.api_input import reject_unknown_fields
from maru.core.problems import DependencyUnavailable
from maru.identity.models import Account

from .parsers import ClosedLogisticsJSONParser
from .queries import (
    authorize_logistics_api_scope,
    authorize_self_offer_history_api_scope,
    list_logistics_activity,
    list_logistics_workspace,
    list_self_offers,
    manifest_for_workspace,
    read_restricted_logistics_contact,
    stage_tech_receiving_manifests,
)
from .serializers import (
    LogisticsActivityProjectionSerializer,
    LogisticsCommandResultSerializer,
    LogisticsManifestProjectionSerializer,
    LogisticsSelfOfferProjectionSerializer,
    LogisticsWorkspaceProjectionSerializer,
    ManifestCreateSerializer,
    ManifestStateSerializer,
    MovementCommandSerializer,
    OfferAcceptSerializer,
    OfferRejectSerializer,
    OfferReviewSerializer,
    OfflineBatchSerializer,
    RestrictedContactReadSerializer,
    RestrictedLogisticsContactProjectionSerializer,
    SelfOfferSubmitSerializer,
    VersionedReasonSerializer,
)
from .services import (
    MANIFEST_MANAGE_CAPABILITY,
    MANIFEST_VIEW_CAPABILITY,
    OFFER_REVIEW_CAPABILITY,
    OFFLINE_RECONCILE_CAPABILITY,
    OPERATIONS_MANAGE_CAPABILITY,
    RESTRICTED_CONTACT_CAPABILITY,
    SELF_OFFER_CAPABILITY,
    WORKSPACE_VIEW_CAPABILITY,
    LogisticsAuthorizationDeniedError,
    LogisticsCommandError,
    LogisticsCommandResult,
    LogisticsContainmentCycleError,
    LogisticsResourceUnavailableError,
    LogisticsRetryConflictError,
    LogisticsStateConflictError,
    LogisticsVersionConflictError,
    ManifestLineInput,
    MovementInput,
    OfferItemInput,
    OfflineOperationInput,
    SubjectLocator,
    change_manifest_state,
    create_logistics_manifest,
    ingest_offline_scan_batch,
    record_logistics_event,
    review_equipment_offer,
    submit_equipment_offer,
    withdraw_equipment_offer,
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
        "Canonical lower-case hyphenated UUID. The key is not accepted in JSON."
    ),
)
_OFFER_REVIEW_REQUEST = PolymorphicProxySerializer(
    component_name="LogisticsOfferReviewRequest",
    serializers={
        "accepted": OfferAcceptSerializer,
        "rejected": OfferRejectSerializer,
    },
    resource_type_field_name="outcome",
)
_COMMAND_RESPONSES = {200: LogisticsCommandResultSerializer}
_CREATE_RESPONSES = {
    200: LogisticsCommandResultSerializer,
    201: LogisticsCommandResultSerializer,
}


@method_decorator(never_cache, name="dispatch")
class PrivateLogisticsAPIView(APIView):
    """Every authenticated Logistics response is private and non-cacheable."""

    parser_classes = (ClosedLogisticsJSONParser,)


class LogisticsConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The logistics operation conflicts with current state."
    default_code = "logistics_conflict"

    def __init__(self, *, code: str) -> None:
        super().__init__(
            detail=cast(Any, {"detail": self.default_detail, "code": code}),
            code=code,
        )


def _account(request: Request) -> Account:
    account = request.user
    if not isinstance(account, Account) or not account.is_active:
        raise PermissionDenied(
            "The requested logistics workspace is unavailable.",
            code=LogisticsAuthorizationDeniedError.reason_code,
        )
    return account


def _deny() -> Never:
    raise PermissionDenied(
        "The requested logistics workspace is unavailable.",
        code=LogisticsAuthorizationDeniedError.reason_code,
    )


def _idempotency_key(request: Request) -> UUID:
    raw_value = request.headers.get(IDEMPOTENCY_HEADER)
    if (
        raw_value is None
        or not raw_value
        or raw_value != raw_value.strip()
        or len(raw_value) > MAX_IDEMPOTENCY_HEADER_LENGTH
    ):
        raise ApiValidationError(
            {IDEMPOTENCY_HEADER: ["Provide one canonical UUID."]},
            code="invalid_idempotency_key",
        )
    candidate = raw_value.strip()
    try:
        value = UUID(candidate)
    except ValueError as error:
        raise ApiValidationError(
            {IDEMPOTENCY_HEADER: ["Provide one canonical UUID."]},
            code="invalid_idempotency_key",
        ) from error
    if str(value) != candidate:
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
        {"non_field_errors": ["The logistics input is invalid."]},
        code="logistics_input_invalid",
    ) from error


def _execute[Result](command: Callable[[], Result]) -> Result:
    try:
        return command()
    except LogisticsAuthorizationDeniedError:
        _deny()
    except LogisticsResourceUnavailableError as error:
        raise NotFound(
            "The requested logistics record is unavailable.",
            code=error.reason_code,
        ) from error
    except (
        LogisticsVersionConflictError,
        LogisticsRetryConflictError,
        LogisticsStateConflictError,
        LogisticsContainmentCycleError,
    ) as error:
        raise LogisticsConflict(code=error.reason_code) from error
    except DjangoValidationError as error:
        _django_validation(error)
    except IntegrityError as error:
        raise LogisticsConflict(code=LogisticsStateConflictError.reason_code) from error
    except (DatabaseError, LogisticsCommandError) as error:
        raise DependencyUnavailable from error


def _preauthorize(
    request: Request,
    *,
    organization_id: UUID,
    capability_code: str,
    edition_id: UUID | None = None,
    manifest_id: UUID | None = None,
    offer_id: UUID | None = None,
    address_id: UUID | None = None,
    require_self_offer_open: bool = False,
) -> Account:
    actor = _account(request)
    _execute(
        lambda: authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            capability_code=capability_code,
            edition_id=edition_id,
            manifest_id=manifest_id,
            offer_id=offer_id,
            address_id=address_id,
            require_self_offer_open=require_self_offer_open,
        )
    )
    return actor


def _preauthorize_self_history(
    request: Request, *, organization_id: UUID, edition_id: UUID
) -> Account:
    actor = _account(request)
    _execute(
        lambda: authorize_self_offer_history_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    )
    return actor


def _result_response(
    result: LogisticsCommandResult, *, created: bool = False
) -> Response:
    payload = LogisticsCommandResultSerializer(asdict(result)).data
    response_status = (
        status.HTTP_201_CREATED
        if created and not result.replayed
        else status.HTTP_200_OK
    )
    return Response(payload, status=response_status)


def _subject(values: dict[str, object]) -> SubjectLocator:
    return SubjectLocator(
        kind=str(values["kind"]),
        object_id=cast(UUID, values["object_id"]),
    )


class MyEquipmentOfferCollectionView(PrivateLogisticsAPIView):
    @extend_schema(
        request=None,
        responses={200: LogisticsSelfOfferProjectionSerializer(many=True)},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _preauthorize_self_history(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = _execute(
            lambda: list_self_offers(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        return Response([asdict(item) for item in projection])

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=SelfOfferSubmitSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=SELF_OFFER_CAPABILITY,
            require_self_offer_open=True,
        )
        values = _validated(request, SelfOfferSubmitSerializer)
        item_values = cast(list[dict[str, object]], values["items"])
        result = _execute(
            lambda: submit_equipment_offer(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                title=str(values["title"]),
                description=str(values.get("description", "")),
                pickup_label=str(values["pickup_label"]),
                pickup_recipient_name=str(values.get("pickup_recipient_name", "")),
                pickup_postal_address=str(values["pickup_postal_address"]),
                pickup_access_instructions=str(
                    values.get("pickup_access_instructions", "")
                ),
                pickup_retention_until=cast(Any, values["pickup_retention_until"]),
                available_from=cast(Any, values["available_from"]),
                available_until=cast(Any, values["available_until"]),
                requested_return_at=cast(Any, values.get("requested_return_at")),
                items=tuple(
                    OfferItemInput(
                        kind=str(item["kind"]),
                        name=str(item["name"]),
                        description=str(item.get("description", "")),
                        quantity=cast(int, item["quantity"]),
                        manufacturer=str(item.get("manufacturer", "")),
                        model_name=str(item.get("model_name", "")),
                        serial_number=str(item.get("serial_number", "")),
                        condition=str(item["condition"]),
                        value_class=str(item.get("value_class", "")),
                        ownership_statement=str(item["ownership_statement"]),
                    )
                    for item in item_values
                ),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class MyEquipmentOfferWithdrawView(PrivateLogisticsAPIView):
    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=VersionedReasonSerializer,
        responses=_COMMAND_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        offer_id: UUID,
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            offer_id=offer_id,
            capability_code=SELF_OFFER_CAPABILITY,
        )
        values = _validated(request, VersionedReasonSerializer)
        result = _execute(
            lambda: withdraw_equipment_offer(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                offer_id=offer_id,
                expected_version=cast(int, values["expected_version"]),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class LogisticsWorkspaceView(PrivateLogisticsAPIView):
    @extend_schema(
        request=None,
        responses={200: LogisticsWorkspaceProjectionSerializer},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=WORKSPACE_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = _execute(
            lambda: list_logistics_workspace(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        return Response(asdict(projection))


class EquipmentOfferReviewView(PrivateLogisticsAPIView):
    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=_OFFER_REVIEW_REQUEST,
        responses=_COMMAND_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        offer_id: UUID,
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            offer_id=offer_id,
            capability_code=OFFER_REVIEW_CAPABILITY,
        )
        values = _validated(request, OfferReviewSerializer)
        result = _execute(
            lambda: review_equipment_offer(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                offer_id=offer_id,
                expected_version=cast(int, values["expected_version"]),
                outcome=str(values["outcome"]),
                responsible_department_id=cast(
                    UUID | None, values.get("responsible_department_id")
                ),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class LogisticsMovementView(PrivateLogisticsAPIView):
    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=MovementCommandSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=OPERATIONS_MANAGE_CAPABILITY,
        )
        values = _validated(request, MovementCommandSerializer)
        movement_values = cast(dict[str, object], values["movement"])
        subject_values = cast(dict[str, object], movement_values["subject"])
        movement = MovementInput(
            event_type=str(movement_values["event_type"]),
            subject=_subject(subject_values),
            occurred_at=cast(Any, movement_values["occurred_at"]),
            source_node_id=cast(UUID | None, movement_values.get("source_node_id")),
            destination_node_id=cast(
                UUID | None, movement_values.get("destination_node_id")
            ),
            to_custodian_account_id=cast(
                UUID | None, movement_values.get("to_custodian_account_id")
            ),
            to_custodian_party_id=cast(
                UUID | None, movement_values.get("to_custodian_party_id")
            ),
            quantity=cast(int | None, movement_values.get("quantity")),
            condition_before=str(movement_values.get("condition_before", "")),
            condition_after=str(movement_values.get("condition_after", "")),
            manifest_id=cast(UUID | None, movement_values.get("manifest_id")),
            evidence_reference=str(movement_values.get("evidence_reference", "")),
        )
        result = _execute(
            lambda: record_logistics_event(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                movement=movement,
                expected_sequence=cast(int, values["expected_sequence"]),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class LogisticsManifestCollectionView(PrivateLogisticsAPIView):
    @extend_schema(
        request=None,
        responses={200: LogisticsManifestProjectionSerializer(many=True)},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=WORKSPACE_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        workspace = _execute(
            lambda: list_logistics_workspace(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        return Response([asdict(manifest) for manifest in workspace.manifests])

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=ManifestCreateSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=OPERATIONS_MANAGE_CAPABILITY,
        )
        values = _validated(request, ManifestCreateSerializer)
        line_values = cast(list[dict[str, object]], values["lines"])
        result = _execute(
            lambda: create_logistics_manifest(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                responsible_department_id=cast(
                    UUID, values["responsible_department_id"]
                ),
                manifest_number=str(values["manifest_number"]),
                kind=str(values["kind"]),
                title=str(values["title"]),
                source_node_id=cast(UUID | None, values.get("source_node_id")),
                destination_node_id=cast(
                    UUID | None, values.get("destination_node_id")
                ),
                vehicle_id=cast(UUID | None, values.get("vehicle_id")),
                provider_id=cast(UUID | None, values.get("provider_id")),
                loading_starts_at=cast(Any, values.get("loading_starts_at")),
                loading_ends_at=cast(Any, values.get("loading_ends_at")),
                lines=tuple(
                    ManifestLineInput(
                        subject=_subject(cast(dict[str, object], line["subject"])),
                        quantity=cast(int, line["quantity"]),
                        packed_in_node_id=cast(
                            UUID | None, line.get("packed_in_node_id")
                        ),
                        notes=str(line.get("notes", "")),
                    )
                    for line in line_values
                ),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class LogisticsManifestDetailView(PrivateLogisticsAPIView):
    @extend_schema(
        request=None,
        responses={200: LogisticsManifestProjectionSerializer},
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        manifest_id: UUID,
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            capability_code=MANIFEST_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = _execute(
            lambda: manifest_for_workspace(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                manifest_id=manifest_id,
            )
        )
        return Response(asdict(projection))


class LogisticsManifestStateView(PrivateLogisticsAPIView):
    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=ManifestStateSerializer,
        responses=_COMMAND_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        manifest_id: UUID,
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            capability_code=MANIFEST_MANAGE_CAPABILITY,
        )
        values = _validated(request, ManifestStateSerializer)
        result = _execute(
            lambda: change_manifest_state(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                manifest_id=manifest_id,
                expected_version=cast(int, values["expected_version"]),
                action=str(values["action"]),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class OfflineScanBatchView(PrivateLogisticsAPIView):
    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=OfflineBatchSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=OFFLINE_RECONCILE_CAPABILITY,
        )
        values = _validated(request, OfflineBatchSerializer)
        operation_values = cast(list[dict[str, object]], values["operations"])
        result = _execute(
            lambda: ingest_offline_scan_batch(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                device_code=str(values["device_code"]),
                snapshot_version=cast(int, values["snapshot_version"]),
                policy_version=str(values["policy_version"]),
                expires_at=cast(Any, values["expires_at"]),
                operations=tuple(
                    OfflineOperationInput(
                        sequence=cast(int, operation["sequence"]),
                        idempotency_key=cast(UUID, operation["idempotency_key"]),
                        expected_subject_sequence=cast(
                            int, operation["expected_subject_sequence"]
                        ),
                        action=str(operation["action"]),
                        label_code=str(operation["label_code"]),
                        occurred_at=cast(Any, operation["occurred_at"]),
                        source_label_code=str(operation.get("source_label_code", "")),
                        destination_label_code=str(
                            operation.get("destination_label_code", "")
                        ),
                        quantity=cast(int | None, operation.get("quantity")),
                        observed_condition=str(operation.get("observed_condition", "")),
                    )
                    for operation in operation_values
                ),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="offline",
            )
        )
        return _result_response(result, created=True)


class StageTechReceivingView(PrivateLogisticsAPIView):
    @extend_schema(
        request=None,
        responses={200: LogisticsManifestProjectionSerializer(many=True)},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=WORKSPACE_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = _execute(
            lambda: stage_tech_receiving_manifests(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        return Response([asdict(manifest) for manifest in projection])


class LogisticsActivityView(PrivateLogisticsAPIView):
    @extend_schema(
        request=None,
        responses={200: LogisticsActivityProjectionSerializer(many=True)},
    )
    def get(
        self, request: Request, organization_id: UUID, edition_id: UUID
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=WORKSPACE_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = _execute(
            lambda: list_logistics_activity(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
        return Response([asdict(event) for event in projection])


class RestrictedLogisticsContactView(PrivateLogisticsAPIView):
    @extend_schema(
        request=RestrictedContactReadSerializer,
        responses={200: RestrictedLogisticsContactProjectionSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        address_id: UUID,
    ) -> Response:
        actor = _preauthorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            address_id=address_id,
            capability_code=RESTRICTED_CONTACT_CAPABILITY,
        )
        values = _validated(request, RestrictedContactReadSerializer)
        projection = _execute(
            lambda: read_restricted_logistics_contact(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                address_id=address_id,
                purpose=str(values["purpose"]),
                access_purpose=str(values["access_purpose"]),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return Response(asdict(projection))
