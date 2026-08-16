"""Strict versioned API boundaries for charity partner governance."""

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

from .authorization import resolve_charity_selection_target
from .queries import (
    list_charity_partners,
    list_charity_selection_queue,
    load_charity_selection_review,
    public_charities_for_edition,
)
from .serializers import (
    CharityCommandResultSerializer,
    CharityMediaAddSerializer,
    CharityMediaApproveSerializer,
    CharityMediaWithdrawSerializer,
    CharityPartnerCreateSerializer,
    CharityPartnerSummarySerializer,
    CharityPartnerUpdateSerializer,
    CharitySelectionCommentSerializer,
    CharitySelectionDecisionSerializer,
    CharitySelectionProposeSerializer,
    CharitySelectionPublishSerializer,
    CharitySelectionReviewSerializer,
    CharitySelectionSummarySerializer,
    PublicCharitySerializer,
)
from .services import (
    PARTNER_MANAGE_CAPABILITY,
    PARTNER_VIEW_CAPABILITY,
    QUEUE_VIEW_CAPABILITY,
    SELECTION_COMMENT_CAPABILITY,
    SELECTION_PROPOSE_CAPABILITY,
    SELECTION_PUBLISH_CAPABILITY,
    SELECTION_REVIEW_CAPABILITY,
    SELECTION_VIEW_CAPABILITY,
    CharityAuthorizationDeniedError,
    CharityCommandError,
    CharityIndependentApprovalError,
    CharityPartnerProfile,
    CharityResourceUnavailableError,
    CharityRetryConflictError,
    CharityStateConflictError,
    CharityVersionConflictError,
    add_charity_partner_media,
    add_charity_selection_private_comment,
    approve_charity_partner_media,
    confirm_charity_selection,
    create_charity_partner,
    propose_charity_selection,
    publish_charity_selection,
    reject_charity_selection,
    submit_charity_selection,
    update_charity_partner,
    withdraw_charity_partner_media,
    withdraw_charity_selection_publication,
)

IDEMPOTENCY_HEADER = "Idempotency-Key"
MAX_IDEMPOTENCY_HEADER_LENGTH = 64
CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)

_CHARITY_IDEMPOTENCY_PARAMETER = OpenApiParameter(
    name=IDEMPOTENCY_HEADER,
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    pattern=CANONICAL_UUID_PATTERN,
    description=(
        "Canonical lower-case UUID. An exact same-intent retry recovers the "
        "original command result."
    ),
)

_CHARITY_MEDIA_ACTION_PARAMETER = OpenApiParameter(
    name="action",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    required=True,
    enum=("approve", "withdraw"),
    description="The closed governed-media command selected by this route.",
)

_CHARITY_SELECTION_ACTION_PARAMETER = OpenApiParameter(
    name="action",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    required=True,
    enum=("submit", "confirm", "reject", "comment", "publish", "withdraw"),
    description="The closed selection command selected by this route.",
)

_CHARITY_MEDIA_COMMAND_REQUEST = PolymorphicProxySerializer(
    component_name="CharityMediaCommandRequest",
    serializers=[CharityMediaApproveSerializer, CharityMediaWithdrawSerializer],
    resource_type_field_name=None,
)

_CHARITY_SELECTION_COMMAND_REQUEST = PolymorphicProxySerializer(
    component_name="CharitySelectionCommandRequest",
    serializers=[
        CharitySelectionDecisionSerializer,
        CharitySelectionCommentSerializer,
        CharitySelectionPublishSerializer,
    ],
    resource_type_field_name=None,
)


class CharityConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The charity operation conflicts with current state."
    default_code = "charity_conflict"

    def __init__(self, *, code: str) -> None:
        super().__init__(
            detail=cast(
                Any,
                {"detail": self.default_detail, "code": code},
            ),
            code=code,
        )


def _account(request: Request) -> Account:
    account = request.user
    if not isinstance(account, Account) or not account.is_active:
        raise PermissionDenied(
            "The requested charity workspace is unavailable.",
            code=CharityAuthorizationDeniedError.reason_code,
        )
    return account


def _deny() -> Never:
    raise PermissionDenied(
        "The requested charity workspace is unavailable.",
        code=CharityAuthorizationDeniedError.reason_code,
    )


def _authorize_organization(
    request: Request,
    *,
    organization_id: UUID,
    capability_code: str,
) -> Account:
    account = _account(request)
    target = resolve_organization_target(organization_id=organization_id)
    if not decide(
        principal=account,
        capability_code=capability_code,
        resource=target,
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
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if not decide(
        principal=account,
        capability_code=capability_code,
        resource=target,
    ).allowed:
        _deny()
    return account


def _authorize_selection(
    request: Request,
    *,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
    capability_code: str,
) -> Account:
    account = _account(request)
    target = resolve_charity_selection_target(
        organization_id=organization_id,
        edition_id=edition_id,
        selection_id=selection_id,
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
        or raw_value.strip() != raw_value
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
    reject_unknown_fields(
        request.data,
        allowed_fields=frozenset(serializer.fields),
    )
    serializer.is_valid(raise_exception=True)
    return cast(Payload, serializer.validated_data)


def _django_validation(error: DjangoValidationError) -> Never:
    if hasattr(error, "message_dict"):
        raise ApiValidationError(error.message_dict) from error
    raise ApiValidationError(
        {"non_field_errors": ["The charity input is invalid."]},
        code="charity_input_invalid",
    ) from error


def _execute[Result](command: Callable[[], Result]) -> Result:
    try:
        return command()
    except CharityAuthorizationDeniedError:
        _deny()
    except CharityResourceUnavailableError as error:
        raise NotFound(
            "The requested charity record is unavailable.",
            code=error.reason_code,
        ) from error
    except (
        CharityVersionConflictError,
        CharityRetryConflictError,
        CharityStateConflictError,
        CharityIndependentApprovalError,
    ) as error:
        raise CharityConflict(code=error.reason_code) from error
    except DjangoValidationError as error:
        _django_validation(error)
    except IntegrityError as error:
        raise CharityConflict(code=CharityStateConflictError.reason_code) from error
    except DatabaseError as error:
        raise DependencyUnavailable from error
    except CharityCommandError as error:
        raise DependencyUnavailable from error


def _result_response(result: Any, *, created: bool = False) -> Response:
    payload = CharityCommandResultSerializer(asdict(result)).data
    response_status = (
        status.HTTP_201_CREATED
        if created and not result.replayed
        else status.HTTP_200_OK
    )
    return Response(payload, status=response_status)


class PublicCharityListView(APIView):
    permission_classes = (AllowAny,)

    @extend_schema(
        operation_id="charities_list_public",
        auth=[],
        responses={200: PublicCharitySerializer(many=True)},
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = public_charities_for_edition(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        return Response(PublicCharitySerializer(cast(Any, projection), many=True).data)


@method_decorator(never_cache, name="dispatch")
class PrivateCharityAPIView(APIView):
    """Keep authenticated charity data and safe errors out of shared caches."""


class CharityPartnerCollectionView(PrivateCharityAPIView):
    @extend_schema(
        operation_id="charities_list_partners",
        responses={200: CharityPartnerSummarySerializer(many=True)},
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PARTNER_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = list_charity_partners(
            actor=actor,
            organization_id=organization_id,
            reason="charity_partner_api_directory",
            correlation_id=_correlation_id(request),
            source_channel="api",
        )
        return Response(
            CharityPartnerSummarySerializer(cast(Any, projection), many=True).data
        )

    @extend_schema(
        operation_id="charities_create_partner",
        parameters=[_CHARITY_IDEMPOTENCY_PARAMETER],
        request=CharityPartnerCreateSerializer,
        responses={
            200: CharityCommandResultSerializer,
            201: CharityCommandResultSerializer,
        },
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PARTNER_MANAGE_CAPABILITY,
        )
        idempotency_key = _idempotency_key(request)
        values = _validated(request, CharityPartnerCreateSerializer)
        profile_fields = {
            field_name: str(values.get(field_name, ""))
            for field_name in CharityPartnerProfile.__dataclass_fields__
        }
        result = _execute(
            lambda: create_charity_partner(
                actor=actor,
                organization_id=organization_id,
                slug=str(values["slug"]),
                profile=CharityPartnerProfile(**profile_fields),
                reason=str(values["reason"]),
                idempotency_key=idempotency_key,
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class CharityPartnerDetailView(PrivateCharityAPIView):
    @extend_schema(
        operation_id="charities_update_partner",
        parameters=[_CHARITY_IDEMPOTENCY_PARAMETER],
        request=CharityPartnerUpdateSerializer,
        responses={200: CharityCommandResultSerializer},
    )
    def patch(
        self,
        request: Request,
        organization_id: UUID,
        partner_id: UUID,
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PARTNER_MANAGE_CAPABILITY,
        )
        idempotency_key = _idempotency_key(request)
        values = _validated(request, CharityPartnerUpdateSerializer)
        changes = {
            key: str(value)
            for key, value in values.items()
            if key not in {"expected_version", "reason"}
        }
        result = _execute(
            lambda: update_charity_partner(
                actor=actor,
                organization_id=organization_id,
                partner_id=partner_id,
                expected_version=cast(int, values["expected_version"]),
                changes=changes,
                reason=str(values["reason"]),
                idempotency_key=idempotency_key,
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result)


class CharityMediaCollectionView(PrivateCharityAPIView):
    @extend_schema(
        operation_id="charities_add_media",
        parameters=[_CHARITY_IDEMPOTENCY_PARAMETER],
        request=CharityMediaAddSerializer,
        responses={
            200: CharityCommandResultSerializer,
            201: CharityCommandResultSerializer,
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        partner_id: UUID,
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PARTNER_MANAGE_CAPABILITY,
        )
        idempotency_key = _idempotency_key(request)
        values = _validated(request, CharityMediaAddSerializer)
        result = _execute(
            lambda: add_charity_partner_media(
                actor=actor,
                organization_id=organization_id,
                partner_id=partner_id,
                kind=str(values["kind"]),
                source_reference=str(values["source_reference"]),
                owner_name=str(values["owner_name"]),
                license_basis=str(values["license_basis"]),
                usage_scope=str(values["usage_scope"]),
                attribution=str(values.get("attribution", "")),
                expires_at=cast(Any, values.get("expires_at")),
                reason=str(values["reason"]),
                idempotency_key=idempotency_key,
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class CharityMediaCommandView(PrivateCharityAPIView):
    @extend_schema(
        operation_id="charities_command_media",
        parameters=[
            _CHARITY_IDEMPOTENCY_PARAMETER,
            _CHARITY_MEDIA_ACTION_PARAMETER,
        ],
        request=_CHARITY_MEDIA_COMMAND_REQUEST,
        responses={200: CharityCommandResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        partner_id: UUID,
        media_id: UUID,
        action: str,
    ) -> Response:
        actor = _authorize_organization(
            request,
            organization_id=organization_id,
            capability_code=PARTNER_MANAGE_CAPABILITY,
        )
        if action not in {"approve", "withdraw"}:
            raise NotFound("The requested charity operation is unavailable.")
        idempotency_key = _idempotency_key(request)
        if action == "approve":
            values = _validated(request, CharityMediaApproveSerializer)
            result = _execute(
                lambda: approve_charity_partner_media(
                    actor=actor,
                    organization_id=organization_id,
                    partner_id=partner_id,
                    media_id=media_id,
                    expected_version=cast(int, values["expected_version"]),
                    public_reference=str(values["public_reference"]),
                    reason=str(values["reason"]),
                    idempotency_key=idempotency_key,
                    correlation_id=_correlation_id(request),
                    source_channel="api",
                )
            )
        else:
            values = _validated(request, CharityMediaWithdrawSerializer)
            result = _execute(
                lambda: withdraw_charity_partner_media(
                    actor=actor,
                    organization_id=organization_id,
                    partner_id=partner_id,
                    media_id=media_id,
                    expected_version=cast(int, values["expected_version"]),
                    reason=str(values["reason"]),
                    idempotency_key=idempotency_key,
                    correlation_id=_correlation_id(request),
                    source_channel="api",
                )
            )
        return _result_response(result)


class CharitySelectionCollectionView(PrivateCharityAPIView):
    @extend_schema(
        operation_id="charities_list_selections",
        responses={200: CharitySelectionSummarySerializer(many=True)},
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        actor = _authorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=QUEUE_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = list_charity_selection_queue(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        return Response(
            CharitySelectionSummarySerializer(cast(Any, projection), many=True).data
        )

    @extend_schema(
        operation_id="charities_propose_selection",
        parameters=[_CHARITY_IDEMPOTENCY_PARAMETER],
        request=CharitySelectionProposeSerializer,
        responses={
            200: CharityCommandResultSerializer,
            201: CharityCommandResultSerializer,
        },
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        actor = _authorize_edition(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=SELECTION_PROPOSE_CAPABILITY,
        )
        idempotency_key = _idempotency_key(request)
        values = _validated(request, CharitySelectionProposeSerializer)
        result = _execute(
            lambda: propose_charity_selection(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                partner_id=cast(UUID, values["partner_id"]),
                responsible_department_id=cast(
                    UUID, values["responsible_department_id"]
                ),
                reason=str(values["reason"]),
                idempotency_key=idempotency_key,
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return _result_response(result, created=True)


class CharitySelectionDetailView(PrivateCharityAPIView):
    @extend_schema(
        operation_id="charities_retrieve_selection",
        responses={200: CharitySelectionReviewSerializer},
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        selection_id: UUID,
    ) -> Response:
        actor = _authorize_selection(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            selection_id=selection_id,
            capability_code=SELECTION_VIEW_CAPABILITY,
        )
        reject_unknown_fields(request.query_params, allowed_fields=frozenset())
        projection = _execute(
            lambda: load_charity_selection_review(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                selection_id=selection_id,
                reason="charity_selection_review",
                correlation_id=_correlation_id(request),
                source_channel="api",
            )
        )
        return Response(CharitySelectionReviewSerializer(cast(Any, projection)).data)


_SELECTION_ACTION_CAPABILITIES = {
    "submit": SELECTION_PROPOSE_CAPABILITY,
    "confirm": SELECTION_REVIEW_CAPABILITY,
    "reject": SELECTION_REVIEW_CAPABILITY,
    "comment": SELECTION_COMMENT_CAPABILITY,
    "publish": SELECTION_PUBLISH_CAPABILITY,
    "withdraw": SELECTION_PUBLISH_CAPABILITY,
}


class CharitySelectionCommandView(PrivateCharityAPIView):
    @extend_schema(
        operation_id="charities_command_selection",
        parameters=[
            _CHARITY_IDEMPOTENCY_PARAMETER,
            _CHARITY_SELECTION_ACTION_PARAMETER,
        ],
        request=_CHARITY_SELECTION_COMMAND_REQUEST,
        responses={200: CharityCommandResultSerializer},
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        selection_id: UUID,
        action: str,
    ) -> Response:
        capability_code = _SELECTION_ACTION_CAPABILITIES.get(action)
        if action == "submit":
            actor = _authorize_edition(
                request,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=SELECTION_PROPOSE_CAPABILITY,
            )
        else:
            actor = _authorize_selection(
                request,
                organization_id=organization_id,
                edition_id=edition_id,
                selection_id=selection_id,
                capability_code=capability_code or SELECTION_VIEW_CAPABILITY,
            )
        if capability_code is None:
            raise NotFound("The requested charity operation is unavailable.")
        idempotency_key = _idempotency_key(request)
        correlation_id = _correlation_id(request)
        if action == "comment":
            values = _validated(request, CharitySelectionCommentSerializer)
            result = _execute(
                lambda: add_charity_selection_private_comment(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    selection_id=selection_id,
                    expected_version=cast(int, values["expected_version"]),
                    private_comment=str(values["private_comment"]),
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    source_channel="api",
                )
            )
        elif action == "publish":
            values = _validated(request, CharitySelectionPublishSerializer)
            result = _execute(
                lambda: publish_charity_selection(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    selection_id=selection_id,
                    expected_version=cast(int, values["expected_version"]),
                    media_ids=cast(list[UUID], values.get("media_ids", [])),
                    reason=str(values["reason"]),
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    source_channel="api",
                )
            )
        else:
            values = _validated(request, CharitySelectionDecisionSerializer)
            expected_version = cast(int, values["expected_version"])
            reason = str(values["reason"])
            if action == "submit":
                result = _execute(
                    lambda: submit_charity_selection(
                        actor=actor,
                        organization_id=organization_id,
                        edition_id=edition_id,
                        selection_id=selection_id,
                        expected_version=expected_version,
                        reason=reason,
                        idempotency_key=idempotency_key,
                        correlation_id=correlation_id,
                        source_channel="api",
                    )
                )
            elif action == "confirm":
                result = _execute(
                    lambda: confirm_charity_selection(
                        actor=actor,
                        organization_id=organization_id,
                        edition_id=edition_id,
                        selection_id=selection_id,
                        expected_version=expected_version,
                        reason=reason,
                        idempotency_key=idempotency_key,
                        correlation_id=correlation_id,
                        source_channel="api",
                    )
                )
            elif action == "reject":
                result = _execute(
                    lambda: reject_charity_selection(
                        actor=actor,
                        organization_id=organization_id,
                        edition_id=edition_id,
                        selection_id=selection_id,
                        expected_version=expected_version,
                        reason=reason,
                        idempotency_key=idempotency_key,
                        correlation_id=correlation_id,
                        source_channel="api",
                    )
                )
            else:
                result = _execute(
                    lambda: withdraw_charity_selection_publication(
                        actor=actor,
                        organization_id=organization_id,
                        edition_id=edition_id,
                        selection_id=selection_id,
                        expected_version=expected_version,
                        reason=reason,
                        idempotency_key=idempotency_key,
                        correlation_id=correlation_id,
                        source_channel="api",
                    )
                )
        return _result_response(result)
