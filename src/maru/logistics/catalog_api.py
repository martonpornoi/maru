"""Strict API adapters for governed logistics catalog commands."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Never, cast
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.core.api_input import reject_unknown_fields
from maru.core.problems import DependencyUnavailable
from maru.identity.models import Account

from .catalog_serializers import (
    AssetAgreementCreateSerializer,
    KeyholderAssignSerializer,
    LogisticsLabelCreateSerializer,
    LogisticsNodeCreateSerializer,
    LogisticsPartyCreateSerializer,
    ManifestLineAddSerializer,
    ManifestReceiptSerializer,
    PhysicalKeyCreateSerializer,
    RestrictedAddressCreateSerializer,
    ReusableKitCreateSerializer,
    SerializedAssetCreateSerializer,
    StockLotCreateSerializer,
)
from .parsers import ClosedLogisticsJSONParser
from .queries import authorize_logistics_api_scope
from .serializers import LogisticsCommandResultSerializer
from .services import (
    CATALOG_MANAGE_CAPABILITY,
    MANIFEST_MANAGE_CAPABILITY,
    KitLineInput,
    LogisticsAuthorizationDeniedError,
    LogisticsCommandError,
    LogisticsCommandResult,
    LogisticsContainmentCycleError,
    LogisticsResourceUnavailableError,
    LogisticsRetryConflictError,
    LogisticsStateConflictError,
    LogisticsVersionConflictError,
    ManifestLineInput,
    PartyProfile,
    SubjectLocator,
    add_manifest_line,
    assign_keyholder_responsibility,
    create_logistics_label,
    create_logistics_node,
    create_logistics_party,
    create_restricted_logistics_address,
    create_reusable_kit,
    record_asset_agreement,
    record_manifest_receipt,
    register_physical_key,
    register_serialized_asset,
    register_stock_lot,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from rest_framework.request import Request

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
_COMMAND_RESPONSES = {200: LogisticsCommandResultSerializer}
_CREATE_RESPONSES = {
    200: LogisticsCommandResultSerializer,
    201: LogisticsCommandResultSerializer,
}


class LogisticsCatalogConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The logistics catalog operation conflicts with current state."
    default_code = "logistics_conflict"

    def __init__(self, *, code: str) -> None:
        """Initialize the LogisticsCatalogConflict instance.

        Parameters
        ----------
        code : str
            The machine-readable reason for the catalog conflict.
        """
        super().__init__(
            detail=cast("Any", {"detail": self.default_detail, "code": code}),
            code=code,
        )


def _account(request: Request) -> Account:
    account = request.user
    if not isinstance(account, Account) or not account.is_active:
        raise PermissionDenied(
            "The requested logistics catalog is unavailable.",
            code=LogisticsAuthorizationDeniedError.reason_code,
        )
    return account


def _deny() -> Never:
    raise PermissionDenied(
        "The requested logistics catalog is unavailable.",
        code=LogisticsAuthorizationDeniedError.reason_code,
    )


def _authorize(
    request: Request,
    *,
    organization_id: UUID,
    capability_code: str,
    edition_id: UUID | None = None,
    manifest_id: UUID | None = None,
    manifest_line_id: UUID | None = None,
    key_id: UUID | None = None,
) -> Account:
    """Authorize the exact route target before parsing query, body, or headers.

    Parameters
    ----------
    request : Request
        The incoming HTTP request and authenticated principal context.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    capability_code : str
        The stable capability code required by the operation.
    edition_id : UUID | None, default=None
        The event edition identifier that scopes the operation.
    manifest_id : UUID | None, default=None
        The manifest identifier within the requested scope.
    manifest_line_id : UUID | None, default=None
        The manifest line identifier within the requested scope.
    key_id : UUID | None, default=None
        The key identifier within the requested scope.

    Returns
    -------
    Account
        The resolved Account for authorize.

    Raises
    ------
    DependencyUnavailable
        If the scoped target does not exist or cannot be disclosed.
    """
    actor = _account(request)
    try:
        if manifest_line_id is not None:
            authorize_logistics_api_scope(
                actor=actor,
                organization_id=organization_id,
                capability_code=capability_code,
                edition_id=edition_id,
                manifest_id=manifest_id,
                manifest_line_id=manifest_line_id,
            )
        elif key_id is not None:
            authorize_logistics_api_scope(
                actor=actor,
                organization_id=organization_id,
                capability_code=capability_code,
                edition_id=edition_id,
                manifest_id=manifest_id,
                key_id=key_id,
            )
        else:
            authorize_logistics_api_scope(
                actor=actor,
                organization_id=organization_id,
                capability_code=capability_code,
                edition_id=edition_id,
                manifest_id=manifest_id,
            )
    except LogisticsAuthorizationDeniedError:
        _deny()
    except DatabaseError as error:
        raise DependencyUnavailable from error
    return actor


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
    candidate = raw_value
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
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return uuid4()


def _validated[Payload: dict[str, object]](
    request: Request,
    serializer_class: type[serializers.Serializer[Payload]],
) -> Payload:
    reject_unknown_fields(request.query_params, allowed_fields=frozenset())
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return cast("Payload", serializer.validated_data)


def _django_validation(error: DjangoValidationError) -> Never:
    if hasattr(error, "message_dict"):
        raise ApiValidationError(error.message_dict) from error
    raise ApiValidationError(
        {"non_field_errors": ["The logistics catalog input is invalid."]},
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
        raise LogisticsCatalogConflict(code=error.reason_code) from error
    except DjangoValidationError as error:
        _django_validation(error)
    except IntegrityError as error:
        raise LogisticsCatalogConflict(
            code=LogisticsStateConflictError.reason_code
        ) from error
    except (DatabaseError, LogisticsCommandError) as error:
        raise DependencyUnavailable from error


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
        object_id=cast("UUID", values["object_id"]),
    )


def _optional_uuid(values: dict[str, object], field: str) -> UUID | None:
    return cast("UUID | None", values.get(field))


def _optional_text(values: dict[str, object], field: str) -> str:
    return str(values.get(field, ""))


def _owner(values: dict[str, object]) -> tuple[str, UUID | None, UUID | None]:
    return (
        str(values["kind"]),
        _optional_uuid(values, "account_id"),
        _optional_uuid(values, "party_id"),
    )


@method_decorator(never_cache, name="dispatch")
class PrivateLogisticsCatalogAPIView(APIView):
    """Authenticated logistics API response boundary, including safe errors."""

    parser_classes = (ClosedLogisticsJSONParser,)


class LogisticsPartyCollectionView(PrivateLogisticsCatalogAPIView):
    """Expose logistics party collection through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=LogisticsPartyCreateSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        """Create the logistics party.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )
        values = _validated(request, LogisticsPartyCreateSerializer)
        profile_values = cast("dict[str, object]", values["profile"])
        result = _execute(
            lambda: create_logistics_party(
                actor=actor,
                organization_id=organization_id,
                code=str(values["code"]),
                profile=PartyProfile(
                    kind=str(profile_values["kind"]),
                    role=str(profile_values["role"]),
                    legal_name=str(profile_values["legal_name"]),
                    public_name=str(profile_values["public_name"]),
                    provider_reference=_optional_text(
                        profile_values, "provider_reference"
                    ),
                    website_url=_optional_text(profile_values, "website_url"),
                ),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class RestrictedAddressCollectionView(PrivateLogisticsCatalogAPIView):
    """Expose restricted address collection through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=RestrictedAddressCreateSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID | None = None,
    ) -> Response:
        """Create the restricted logistics address.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID | None, default=None
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )
        values = _validated(request, RestrictedAddressCreateSerializer)
        result = _execute(
            lambda: create_restricted_logistics_address(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                subject_account_id=_optional_uuid(values, "subject_account_id"),
                party_id=_optional_uuid(values, "party_id"),
                purpose=str(values["purpose"]),
                label=str(values["label"]),
                recipient_name=_optional_text(values, "recipient_name"),
                contact_email=_optional_text(values, "contact_email"),
                contact_phone=_optional_text(values, "contact_phone"),
                postal_address=str(values["postal_address"]),
                access_instructions=_optional_text(values, "access_instructions"),
                retention_until=cast("Any", values.get("retention_until")),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class LogisticsNodeCollectionView(PrivateLogisticsCatalogAPIView):
    """Expose logistics node collection through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=LogisticsNodeCreateSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID | None = None,
    ) -> Response:
        """Create the logistics node.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID | None, default=None
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )
        values = _validated(request, LogisticsNodeCreateSerializer)
        result = _execute(
            lambda: create_logistics_node(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                kind=str(values["kind"]),
                code=str(values["code"]),
                name=str(values["name"]),
                description=_optional_text(values, "description"),
                storage_address_id=_optional_uuid(values, "storage_address_id"),
                external_owner_id=_optional_uuid(values, "external_owner_id"),
                provider_id=_optional_uuid(values, "provider_id"),
                vehicle_registration=_optional_text(values, "vehicle_registration"),
                venue_space_selection_id=_optional_uuid(
                    values, "venue_space_selection_id"
                ),
                capacity_note=_optional_text(values, "capacity_note"),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class SerializedAssetCollectionView(PrivateLogisticsCatalogAPIView):
    """Expose serialized asset collection through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=SerializedAssetCreateSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID | None = None,
    ) -> Response:
        """Register the serialized asset.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID | None, default=None
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )
        values = _validated(request, SerializedAssetCreateSerializer)
        owner_values = cast("dict[str, object]", values["owner"])
        owner_kind, owner_account_id, owner_party_id = _owner(owner_values)
        result = _execute(
            lambda: register_serialized_asset(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                catalog_code=str(values["catalog_code"]),
                name=str(values["name"]),
                asset_type=str(values["asset_type"]),
                manufacturer=_optional_text(values, "manufacturer"),
                model_name=_optional_text(values, "model_name"),
                serial_number=_optional_text(values, "serial_number"),
                acquisition=str(values["acquisition"]),
                value_class=_optional_text(values, "value_class"),
                owner_kind=owner_kind,
                owner_account_id=owner_account_id,
                owner_party_id=owner_party_id,
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class StockLotCollectionView(PrivateLogisticsCatalogAPIView):
    """Expose stock lot collection through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=StockLotCreateSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID | None = None,
    ) -> Response:
        """Register the stock lot.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID | None, default=None
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )
        values = _validated(request, StockLotCreateSerializer)
        owner_values = cast("dict[str, object]", values["owner"])
        owner_kind, owner_account_id, owner_party_id = _owner(owner_values)
        result = _execute(
            lambda: register_stock_lot(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                catalog_code=str(values["catalog_code"]),
                name=str(values["name"]),
                stock_type=str(values["stock_type"]),
                unit=str(values["unit"]),
                initial_quantity=cast("int", values["initial_quantity"]),
                value_class=_optional_text(values, "value_class"),
                owner_kind=owner_kind,
                owner_account_id=owner_account_id,
                owner_party_id=owner_party_id,
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class PhysicalKeyCollectionView(PrivateLogisticsCatalogAPIView):
    """Expose physical key collection through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=PhysicalKeyCreateSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID | None = None,
    ) -> Response:
        """Register the physical key.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID | None, default=None
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )
        values = _validated(request, PhysicalKeyCreateSerializer)
        result = _execute(
            lambda: register_physical_key(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                code=str(values["code"]),
                label=str(values["label"]),
                opens_node_id=cast("UUID", values["opens_node_id"]),
                provider_id=_optional_uuid(values, "provider_id"),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class KeyholderAssignmentView(PrivateLogisticsCatalogAPIView):
    """Expose keyholder assignment through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=KeyholderAssignSerializer,
        responses=_COMMAND_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        key_id: UUID,
    ) -> Response:
        """Assign the keyholder responsibility.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        key_id : UUID
            The key identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
            key_id=key_id,
        )
        values = _validated(request, KeyholderAssignSerializer)
        result = _execute(
            lambda: assign_keyholder_responsibility(
                actor=actor,
                organization_id=organization_id,
                key_id=key_id,
                responsible_account_id=cast("UUID", values["responsible_account_id"]),
                starts_at=cast("Any", values["starts_at"]),
                ends_at=cast("Any", values.get("ends_at")),
                expected_version=cast("int", values["expected_version"]),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class LogisticsLabelCollectionView(PrivateLogisticsCatalogAPIView):
    """Expose logistics label collection through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=LogisticsLabelCreateSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        """Create the logistics label.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )
        values = _validated(request, LogisticsLabelCreateSerializer)
        result = _execute(
            lambda: create_logistics_label(
                actor=actor,
                organization_id=organization_id,
                subject=_subject(cast("dict[str, object]", values["subject"])),
                label_code=str(values["label_code"]),
                qr_identifier=str(values["qr_identifier"]),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class AssetAgreementCollectionView(PrivateLogisticsCatalogAPIView):
    """Expose asset agreement collection through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=AssetAgreementCreateSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID | None = None,
    ) -> Response:
        """Record the asset agreement.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID | None, default=None
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )
        values = _validated(request, AssetAgreementCreateSerializer)
        provider = cast("dict[str, object]", values["provider"])
        borrower = cast("dict[str, object]", values.get("borrower", {}))
        result = _execute(
            lambda: record_asset_agreement(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                subject=_subject(cast("dict[str, object]", values["subject"])),
                kind=str(values["kind"]),
                provider_account_id=_optional_uuid(provider, "account_id"),
                provider_party_id=_optional_uuid(provider, "party_id"),
                borrower_account_id=_optional_uuid(borrower, "account_id"),
                borrower_party_id=_optional_uuid(borrower, "party_id"),
                starts_at=cast("Any", values["starts_at"]),
                ends_at=cast("Any", values["ends_at"]),
                return_due_at=cast("Any", values["return_due_at"]),
                return_address_id=_optional_uuid(values, "return_address_id"),
                provider_reference=_optional_text(values, "provider_reference"),
                terms_reference=_optional_text(values, "terms_reference"),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class ReusableKitCollectionView(PrivateLogisticsCatalogAPIView):
    """Expose reusable kit collection through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=ReusableKitCreateSerializer,
        responses=_CREATE_RESPONSES,
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        """Create the reusable kit.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
        )
        values = _validated(request, ReusableKitCreateSerializer)
        lines = cast("list[dict[str, object]]", values["lines"])
        result = _execute(
            lambda: create_reusable_kit(
                actor=actor,
                organization_id=organization_id,
                code=str(values["code"]),
                name=str(values["name"]),
                description=_optional_text(values, "description"),
                lines=tuple(
                    KitLineInput(
                        subject=_subject(
                            cast("dict[str, object]", line_values["subject"])
                        ),
                        quantity=cast("int", line_values["quantity"]),
                        notes=_optional_text(line_values, "notes"),
                    )
                    for line_values in lines
                ),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class ManifestLineCollectionView(PrivateLogisticsCatalogAPIView):
    """Expose manifest line collection through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=ManifestLineAddSerializer,
        responses=_COMMAND_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        manifest_id: UUID,
    ) -> Response:
        """Add the manifest line.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        manifest_id : UUID
            The manifest identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            capability_code=MANIFEST_MANAGE_CAPABILITY,
        )
        values = _validated(request, ManifestLineAddSerializer)
        line_values = cast("dict[str, object]", values["line"])
        result = _execute(
            lambda: add_manifest_line(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                manifest_id=manifest_id,
                expected_version=cast("int", values["expected_version"]),
                line=ManifestLineInput(
                    subject=_subject(cast("dict[str, object]", line_values["subject"])),
                    quantity=cast("int", line_values["quantity"]),
                    packed_in_node_id=_optional_uuid(line_values, "packed_in_node_id"),
                    notes=_optional_text(line_values, "notes"),
                ),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class ManifestReceiptView(PrivateLogisticsCatalogAPIView):
    """Expose manifest receipt through the HTTP API."""

    @extend_schema(
        parameters=[_IDEMPOTENCY_PARAMETER],
        request=ManifestReceiptSerializer,
        responses=_COMMAND_RESPONSES,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        manifest_id: UUID,
        line_id: UUID,
    ) -> Response:
        """Record the manifest receipt.

        Authenticated logistics API response boundary, including safe errors.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        manifest_id : UUID
            The manifest identifier within the requested scope.
        line_id : UUID
            The line identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        actor = _authorize(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            manifest_line_id=line_id,
            capability_code=MANIFEST_MANAGE_CAPABILITY,
        )
        values = _validated(request, ManifestReceiptSerializer)
        result = _execute(
            lambda: record_manifest_receipt(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                manifest_id=manifest_id,
                line_id=line_id,
                expected_sequence=cast("int", values["expected_sequence"]),
                occurred_at=cast("datetime", values["occurred_at"]),
                condition_after=str(values["condition_after"]),
                reason=str(values["reason"]),
                idempotency_key=_idempotency_key(request),
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


__all__ = [
    "AssetAgreementCollectionView",
    "KeyholderAssignmentView",
    "LogisticsLabelCollectionView",
    "LogisticsNodeCollectionView",
    "LogisticsPartyCollectionView",
    "ManifestLineCollectionView",
    "ManifestReceiptView",
    "PhysicalKeyCollectionView",
    "RestrictedAddressCollectionView",
    "ReusableKitCollectionView",
    "SerializedAssetCollectionView",
    "StockLotCollectionView",
]
