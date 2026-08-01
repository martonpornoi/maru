"""Platform-administrator API for organization-owned convention series."""

from __future__ import annotations

import logging
from typing import Any, Never, cast
from uuid import UUID

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.core.api_input import reject_unknown_fields
from maru.core.pagination import StandardPageNumberPagination
from maru.core.problems import DependencyUnavailable
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from maru.organizations.serializers import (
    ConventionSeriesListQuerySerializer,
    ConventionSeriesProblemSerializer,
    ConventionSeriesReadSerializer,
    ConventionSeriesUpdateSerializer,
)
from maru.organizations.services import (
    ConventionSeriesCreationDetails,
    update_convention_series,
)

logger = logging.getLogger(__name__)


class ConventionSeriesConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The convention series conflicts with current state."
    default_code = "convention_series_conflict"

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


PROBLEM_CONTENT_TYPE = "application/problem+json"


def _problem_response(description: str) -> OpenApiResponse:
    return OpenApiResponse(
        response=ConventionSeriesProblemSerializer,
        description=description,
    )


def _raise_dependency_unavailable(message: str, error: Exception) -> Never:
    logger.exception(message)
    raise DependencyUnavailable from error


def _require_platform_administrator(request: Request) -> Account:
    account = request.user
    if not isinstance(account, Account):
        raise TypeError("Authenticated principal is not a platform account")
    if not account.is_active or not account.is_platform_administrator:
        raise PermissionDenied(
            "Platform administration is required.",
            code="platform_administration_required",
        )
    return account


def _django_validation_code(error: DjangoValidationError) -> str:
    if hasattr(error, "error_dict"):
        for field_errors in error.error_dict.values():
            if field_errors:
                return str(field_errors[0].code or "invalid_convention_series")
    if hasattr(error, "error_list") and error.error_list:
        return str(error.error_list[0].code or "invalid_convention_series")
    return "invalid_convention_series"


def _django_validation_detail(
    error: DjangoValidationError,
) -> dict[str, list[str]] | list[str]:
    if hasattr(error, "message_dict"):
        return error.message_dict
    return [str(message) for message in error.messages]


def _scoped_series_or_not_found(
    *,
    organization_id: UUID,
    series_id: UUID,
) -> ConventionSeries:
    try:
        return ConventionSeries.objects.get(
            id=series_id,
            organization_id=organization_id,
        )
    except ConventionSeries.DoesNotExist as error:
        raise NotFound(
            "The scoped convention series does not exist.",
            code="convention_series_not_found",
        ) from error
    except (DatabaseError, RuntimeError) as error:
        _raise_dependency_unavailable(
            "Unable to load the scoped convention series",
            error,
        )


class ConventionSeriesListView(GenericAPIView[ConventionSeries]):
    serializer_class = ConventionSeriesReadSerializer
    pagination_class = StandardPageNumberPagination

    @extend_schema(
        operation_id="organizations_list_convention_series",
        parameters=[ConventionSeriesListQuerySerializer],
        responses={
            200: ConventionSeriesReadSerializer(many=True),
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The list query is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Platform administration is required."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The organization does not exist."
            ),
            (503, PROBLEM_CONTENT_TYPE): _problem_response(
                "A canonical dependency is temporarily unavailable."
            ),
        },
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        _require_platform_administrator(request)
        query = ConventionSeriesListQuerySerializer(data=request.query_params)
        reject_unknown_fields(
            request.query_params,
            allowed_fields=frozenset(query.fields),
        )
        query.is_valid(raise_exception=True)
        try:
            if not Organization.objects.filter(id=organization_id).exists():
                raise NotFound(
                    "The organization does not exist.",
                    code="organization_not_found",
                )

            series = ConventionSeries.objects.filter(
                organization_id=organization_id,
            ).order_by("name", "id")
            page = self.paginate_queryset(series)
            if page is None:
                raise RuntimeError(  # noqa: TRY301
                    "Convention-series list pagination is required."
                )
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to load the convention-series list",
                error,
            )


class ConventionSeriesDetailView(APIView):
    @extend_schema(
        operation_id="organizations_retrieve_convention_series",
        responses={
            200: ConventionSeriesReadSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The detail query is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Platform administration is required."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The scoped series does not exist."
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
        series_id: UUID,
    ) -> Response:
        _require_platform_administrator(request)
        reject_unknown_fields(
            request.query_params,
            allowed_fields=frozenset(),
        )
        series = _scoped_series_or_not_found(
            organization_id=organization_id,
            series_id=series_id,
        )
        return Response(ConventionSeriesReadSerializer(series).data)

    @extend_schema(
        operation_id="organizations_update_convention_series",
        request=ConventionSeriesUpdateSerializer,
        responses={
            200: ConventionSeriesReadSerializer,
            (400, PROBLEM_CONTENT_TYPE): _problem_response(
                "The complete profile is invalid."
            ),
            (403, PROBLEM_CONTENT_TYPE): _problem_response(
                "Platform administration is required."
            ),
            (404, PROBLEM_CONTENT_TYPE): _problem_response(
                "The scoped series does not exist."
            ),
            (409, PROBLEM_CONTENT_TYPE): _problem_response(
                "The parent is closed or the profile version is stale."
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
        series_id: UUID,
    ) -> Response:
        account = _require_platform_administrator(request)
        _scoped_series_or_not_found(
            organization_id=organization_id,
            series_id=series_id,
        )
        reject_unknown_fields(
            request.data,
            allowed_fields=frozenset(ConventionSeriesUpdateSerializer().fields),
        )
        serializer = ConventionSeriesUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        try:
            result = update_convention_series(
                actor=account,
                organization_id=organization_id,
                series_id=series_id,
                expected_profile_version=cast(
                    int,
                    values["expected_profile_version"],
                ),
                details=ConventionSeriesCreationDetails(
                    name=cast(str, values["name"]),
                    description=cast(str, values["description"]),
                    website_url=cast(str, values["website_url"]),
                    contact_email=cast(str, values["contact_email"]),
                    is_active=cast(bool, values["is_active"]),
                ),
                correlation_id=correlation_id,
                source_channel="api",
            )
        except DjangoPermissionDenied as error:
            raise PermissionDenied(
                "Platform administration is required.",
                code="platform_administration_required",
            ) from error
        except (Organization.DoesNotExist, ConventionSeries.DoesNotExist) as error:
            raise NotFound(
                "The scoped convention series does not exist.",
                code="convention_series_not_found",
            ) from error
        except DjangoValidationError as error:
            code = _django_validation_code(error)
            detail = _django_validation_detail(error)
            if code in {"series_parent_closed", "stale_series_profile"}:
                raise ConventionSeriesConflict(detail=detail, code=code) from error
            raise ApiValidationError(
                cast(
                    Any,
                    {
                        "detail": "The convention-series profile is invalid.",
                        "code": code,
                        "errors": detail,
                    },
                ),
                code=code,
            ) from error
        except (DatabaseError, RuntimeError) as error:
            _raise_dependency_unavailable(
                "Unable to update the convention-series profile",
                error,
            )
        return Response(ConventionSeriesReadSerializer(result.series).data)
