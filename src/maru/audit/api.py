"""Capability-protected, minimized security-audit query."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from maru.audit.models import AuditEvent
from maru.audit.serializers import (
    AuditEventSummarySerializer,
    AuditQuerySerializer,
)
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import decide, resolve_organization_target
from maru.identity.models import Account


def _audit_query_access(
    *,
    account: Account,
    organization_id: UUID,
    correlation_id: UUID,
    outcome: str,
    reason_code: str,
    obligations: tuple[str, ...] = (),
    purpose: str | None = None,
    target_count: int | None = None,
) -> None:
    safe_metadata: dict[str, object] = {
        "policy_version": POLICY_VERSION,
        "route_name": "audit-event-list",
    }
    if purpose is not None:
        safe_metadata["access_purpose"] = purpose
    if target_count is not None:
        safe_metadata["target_count"] = target_count
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=account.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=None,
            capability_code="audit.view_security",
            operation="audit.event.search",
            target_type="audit.event_set",
            target_id=organization_id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="api",
            obligations=obligations,
            safe_metadata=safe_metadata,
            retention_class="security-extended",
        )
    )


class AuditEventListView(APIView):
    """Expose audit event list through the HTTP API."""

    @extend_schema(
        operation_id="audit_list_security_events",
        parameters=[AuditQuerySerializer],
        responses=AuditEventSummarySerializer(many=True),
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        """List the security events.

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
        PermissionDenied
            If the caller lacks permission for the requested scope.
        TypeError
            If the caller supplies an object of an unsupported type.
        """
        account = request.user
        if not isinstance(account, Account):
            raise TypeError("Authenticated principal is not a platform account")
        correlation_id = UUID(request.correlation_id)  # type: ignore[attr-defined]
        decision = decide(
            principal=account,
            capability_code="audit.view_security",
            resource=resolve_organization_target(organization_id=organization_id),
            requested_fields=frozenset(AuditEventSummarySerializer.Meta.fields),
        )
        obligations = tuple(sorted(decision.obligations))
        if not decision.allowed:
            _audit_query_access(
                account=account,
                organization_id=organization_id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=decision.reason_code,
            )
            raise PermissionDenied(
                "You do not have access to this audit scope.",
                code=decision.reason_code,
            )
        projection_fields = frozenset(AuditEventSummarySerializer.Meta.fields)
        if not projection_fields.issubset(decision.fields):
            _audit_query_access(
                account=account,
                organization_id=organization_id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="field_projection_denied",
                obligations=obligations,
            )
            raise PermissionDenied(
                "The permitted audit projection is incomplete.",
                code="field_projection_denied",
            )

        query = AuditQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        events = AuditEvent.objects.filter(organization_id=organization_id)
        if edition_id := values.get("edition_id"):
            events = events.filter(event_edition_id=edition_id)
        if requested_correlation := values.get("correlation_id"):
            events = events.filter(correlation_id=requested_correlation)
        if principal_id := values.get("principal_id"):
            events = events.filter(principal_id=principal_id)
        if outcome := values.get("outcome"):
            events = events.filter(outcome=outcome)
        selected = list(events.order_by("-occurred_at", "-id")[: values["limit"]])
        purpose = str(values["purpose"])
        _audit_query_access(
            account=account,
            organization_id=organization_id,
            correlation_id=correlation_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            obligations=obligations,
            purpose=purpose,
            target_count=len(selected),
        )
        return Response(AuditEventSummarySerializer(selected, many=True).data)
