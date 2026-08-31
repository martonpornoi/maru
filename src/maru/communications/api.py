"""Self-service inbox/preferences and scoped service-delivery failures."""

from uuid import UUID

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
)
from rest_framework.exceptions import (
    ValidationError as ApiValidationError,
)
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.authorization.policy import decide, resolve_edition_target
from maru.communications.models import (
    NotificationDelivery,
    NotificationMessage,
    NotificationPreference,
)
from maru.communications.queries import notification_messages_for_account
from maru.communications.serializers import (
    DeliveryFailureSerializer,
    NotificationMessageSerializer,
    NotificationPreferenceSerializer,
    UpdateNotificationPreferenceSerializer,
)
from maru.communications.services import mark_message_read
from maru.identity.models import Account
from maru.organizations.models import Organization

MARKETING_CONSENT_VERSION = "marketing-email-v1"


def _account(request: Request) -> Account:
    if not isinstance(request.user, Account):
        raise TypeError("Authenticated principal is not a platform account")
    return request.user


class MyNotificationListView(APIView):
    """Expose my notification list through the HTTP API."""

    @extend_schema(
        operation_id="communications_list_my_notifications",
        responses=NotificationMessageSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """List my notifications.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        items = (
            notification_messages_for_account(account=_account(request))
            .prefetch_related("deliveries")
            .order_by("-rendered_at", "-id")[:200]
        )
        return Response(NotificationMessageSerializer(items, many=True).data)


class MyNotificationReadView(APIView):
    """Expose my notification read through the HTTP API."""

    @extend_schema(
        operation_id="communications_mark_my_notification_read",
        request=None,
        responses=NotificationMessageSerializer,
    )
    def post(self, request: Request, message_id: UUID) -> Response:
        """Mark my notification read.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        message_id : UUID
            The message identifier within the requested scope.

        Returns
        -------
        Response
            The HTTP response for the requested operation.

        Raises
        ------
        NotFound
            If the scoped resource is unavailable to the caller.
        """
        try:
            item = mark_message_read(
                account=_account(request),
                message_id=message_id,
            )
        except NotificationMessage.DoesNotExist as error:
            raise NotFound("The message is unavailable.") from error
        return Response(
            NotificationMessageSerializer(
                NotificationMessage.objects.prefetch_related("deliveries").get(
                    id=item.id
                )
            ).data
        )


class MyNotificationPreferenceView(APIView):
    """Expose my notification preference through the HTTP API."""

    @extend_schema(
        operation_id="communications_retrieve_my_preference",
        responses=NotificationPreferenceSerializer,
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        """Retrieve my preference.

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

        Raises
        ------
        NotFound
            If the scoped resource is unavailable to the caller.
        """
        account = _account(request)
        if not Organization.objects.filter(id=organization_id).exists():
            raise NotFound("Notification preferences are unavailable.")
        item, _ = NotificationPreference.objects.get_or_create(
            account=account,
            organization_id=organization_id,
        )
        return Response(NotificationPreferenceSerializer(item).data)

    @extend_schema(
        operation_id="communications_update_my_preference",
        request=UpdateNotificationPreferenceSerializer,
        responses=NotificationPreferenceSerializer,
    )
    def put(self, request: Request, organization_id: UUID) -> Response:
        """Update my preference.

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

        Raises
        ------
        ApiValidationError
            If the request payload violates the endpoint contract.
        """
        account = _account(request)
        serializer = UpdateNotificationPreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        consent = bool(values["marketing_email_consent"])
        version = str(values.get("marketing_consent_version", ""))
        if consent and version != MARKETING_CONSENT_VERSION:
            raise ApiValidationError(
                {
                    "detail": "Review the current marketing consent before opting in.",
                    "code": "marketing_consent_version_mismatch",
                }
            )
        with transaction.atomic():
            item, _ = NotificationPreference.objects.select_for_update().get_or_create(
                account=account,
                organization_id=organization_id,
            )
            item.operational_email_enabled = bool(values["operational_email_enabled"])
            item.marketing_email_consent = consent
            item.marketing_consent_version = version if consent else ""
            item.marketing_consented_at = timezone.now() if consent else None
            item.save()
        return Response(NotificationPreferenceSerializer(item).data)


class StaffDeliveryFailureListView(APIView):
    """Expose staff delivery failure list through the HTTP API."""

    @extend_schema(
        operation_id="communications_list_delivery_failures",
        responses=DeliveryFailureSerializer(many=True),
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        edition_id: UUID,
    ) -> Response:
        """List the delivery failures.

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
        account = _account(request)
        decision = decide(
            principal=account,
            capability_code="registration.view_service_summary",
            resource=resolve_edition_target(
                organization_id=organization_id,
                edition_id=edition_id,
            ),
        )
        if not decision.allowed:
            raise PermissionDenied(
                "Delivery failures are unavailable.",
                code=decision.reason_code,
            )
        deliveries = (
            NotificationDelivery.objects.filter(
                message__organization_id=organization_id,
                message__edition_id=edition_id,
                status=NotificationDelivery.Status.PERMANENT_FAILED,
            )
            .select_related("message")
            .order_by("-last_attempt_at", "-id")[:250]
        )
        rows = [
            {
                "message_id": item.message_id,
                "account_id": item.message.account_id,
                "message_type": item.message.message_type,
                "subject": item.message.subject,
                "channel": item.channel,
                "status": item.status,
                "attempt_count": item.attempt_count,
                "safe_error_code": item.safe_error_code,
                "last_attempt_at": item.last_attempt_at,
            }
            for item in deliveries
        ]
        return Response(
            DeliveryFailureSerializer(
                instance=rows,  # type: ignore[arg-type]
                many=True,
            ).data
        )
