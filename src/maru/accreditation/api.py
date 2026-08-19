"""Credential self-service, staff commands, and offline relay ingestion."""

from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
)
from rest_framework.exceptions import (
    ValidationError as ApiValidationError,
)
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.accreditation.models import (
    Credential,
    OfflineCheckInOperation,
)
from maru.accreditation.serializers import (
    CredentialCommandSerializer,
    CredentialSerializer,
    IssuedCredentialSerializer,
    OfflineCheckInSerializer,
    OfflineManifestSerializer,
    OfflineOperationSerializer,
)
from maru.accreditation.services import (
    generate_offline_manifest,
    issue_credential,
    reconcile_offline_check_in,
    revoke_credential,
)
from maru.authorization.policy import decide, resolve_edition_target
from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account


def _account(request: Request) -> Account:
    if not isinstance(request.user, Account):
        raise TypeError("Authenticated principal is not a platform account")
    return request.user


def _correlation_id(request: Request) -> UUID:
    return UUID(request._request.correlation_id)  # type: ignore[attr-defined]  # noqa: SLF001


class MyCredentialListView(APIView):
    """Expose my credential list through the HTTP API."""

    @extend_schema(
        operation_id="accreditation_list_my_credentials",
        responses=CredentialSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """List my credentials.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        items = Credential.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            account_id=_account(request).id,
        ).order_by("-issue_sequence", "-id")
        return Response(CredentialSerializer(items, many=True).data)


class StaffCredentialIssueView(APIView):
    """Expose staff credential issue through the HTTP API."""

    @extend_schema(
        operation_id="accreditation_issue_credential",
        request=CredentialCommandSerializer,
        responses=IssuedCredentialSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        registration_id: UUID,
    ) -> Response:
        """Issue the credential.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        registration_id : UUID
            The attendee registration identifier within the edition scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        ApiValidationError
            If the request payload violates the endpoint contract.
        NotFound
            If the scoped resource is unavailable to the caller.
        PermissionDenied
            If the caller lacks permission for the requested scope.
        """
        serializer = CredentialCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = issue_credential(
                actor=_account(request),
                organization_id=organization_id,
                edition_id=edition_id,
                registration_id=registration_id,
                reason=serializer.validated_data["reason"],
                correlation_id=_correlation_id(request),
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Credential issuance is unavailable.",
                code=error.reason_code,
            ) from error
        except ObjectDoesNotExist as error:
            raise NotFound("The registration is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The credential could not be issued.",
                    "code": error.code or "credential_issue_invalid",
                }
            ) from error
        return Response(
            {
                "credential": CredentialSerializer(result.credential).data,
                "credential_token": result.raw_token,
            },
            status=201,
        )


class StaffCredentialRevokeView(APIView):
    """Expose staff credential revoke through the HTTP API."""

    @extend_schema(
        operation_id="accreditation_revoke_credential",
        request=CredentialCommandSerializer,
        responses=CredentialSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        credential_id: UUID,
    ) -> Response:
        """Revoke the credential.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        credential_id : UUID
            The credential identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        NotFound
            If the scoped resource is unavailable to the caller.
        PermissionDenied
            If the caller lacks permission for the requested scope.
        """
        serializer = CredentialCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = revoke_credential(
                actor=_account(request),
                organization_id=organization_id,
                edition_id=edition_id,
                credential_id=credential_id,
                reason=serializer.validated_data["reason"],
                correlation_id=_correlation_id(request),
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Credential revocation is unavailable.",
                code=error.reason_code,
            ) from error
        except Credential.DoesNotExist as error:
            raise NotFound("The credential is unavailable.") from error
        return Response(CredentialSerializer(item).data)


class StaffOfflineManifestView(APIView):
    """Expose staff offline manifest through the HTTP API."""

    @extend_schema(
        operation_id="accreditation_generate_offline_manifest",
        request=None,
        responses=OfflineManifestSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """Generate the offline manifest.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        ApiValidationError
            If the request payload violates the endpoint contract.
        PermissionDenied
            If the caller lacks permission for the requested scope.
        """
        try:
            manifest = generate_offline_manifest(
                actor=_account(request),
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=_correlation_id(request),
            )
        except AuthorizationDenied as error:
            raise PermissionDenied(
                "Offline manifests are unavailable.",
                code=error.reason_code,
            ) from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The offline manifest could not be generated.",
                    "code": error.code or "offline_manifest_invalid",
                }
            ) from error
        return Response(OfflineManifestSerializer(manifest).data, status=201)


class OfflineCheckInIngestView(APIView):
    """Expose offline check in ingest through the HTTP API."""

    permission_classes = (AllowAny,)
    authentication_classes: tuple[()] = ()

    @extend_schema(
        operation_id="accreditation_ingest_offline_check_in",
        request=OfflineCheckInSerializer,
        responses=OfflineOperationSerializer,
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
        device_code: str,
    ) -> Response:
        """Ingest the offline check-in batch.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.
        device_code : str
            The public relay-device code within the edition scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        ApiValidationError
            If the request payload violates the endpoint contract.
        NotFound
            If the scoped resource is unavailable to the caller.
        """
        serializer = OfflineCheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            operation = reconcile_offline_check_in(
                organization_id=organization_id,
                edition_id=edition_id,
                device_code=device_code,
                operation_id=values["operation_id"],
                device_sequence=values["device_sequence"],
                manifest_sequence=values["manifest_sequence"],
                raw_credential_token=values["credential_token"],
                occurred_at=values["occurred_at"],
                signature=values["signature"],
            )
        except ObjectDoesNotExist as error:
            raise NotFound("The relay endpoint is unavailable.") from error
        except DjangoValidationError as error:
            raise ApiValidationError(
                {
                    "detail": "The offline operation was rejected.",
                    "code": error.code or "offline_operation_invalid",
                }
            ) from error
        return Response(OfflineOperationSerializer(operation).data)


class StaffOfflineConflictListView(APIView):
    """Expose staff offline conflict list through the HTTP API."""

    @extend_schema(
        operation_id="accreditation_list_offline_conflicts",
        responses=OfflineOperationSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """List the offline conflicts.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        organization_id : UUID
            The organization identifier that owns the requested resource.
        edition_id : UUID
            The event edition identifier that scopes the operation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        PermissionDenied
            If the caller lacks permission for the requested scope.
        """
        decision = decide(
            principal=_account(request),
            capability_code="accreditation.manage_offline",
            resource=resolve_edition_target(
                organization_id=organization_id,
                edition_id=edition_id,
            ),
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Offline conflicts are unavailable.",
                code=decision.reason_code,
            )
        items = OfflineCheckInOperation.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            outcome__in=(
                OfflineCheckInOperation.Outcome.CONFLICT,
                OfflineCheckInOperation.Outcome.REJECTED,
            ),
        ).order_by("-received_at", "-id")[:250]
        return Response(OfflineOperationSerializer(items, many=True).data)
