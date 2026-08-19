"""Minimized audit query input and output projections."""

from typing import Any

from rest_framework import serializers

from maru.audit.models import AuditEvent

AUDIT_ACCESS_PURPOSES = (
    ("security_investigation", "Security investigation"),
    ("privacy_request", "Privacy request"),
    ("compliance_review", "Compliance review"),
    ("subject_support", "Subject support"),
    ("integrity_review", "Integrity review"),
)


class AuditQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize and validate audit query data."""

    purpose = serializers.ChoiceField(choices=AUDIT_ACCESS_PURPOSES)
    edition_id = serializers.UUIDField(required=False)
    correlation_id = serializers.UUIDField(required=False)
    principal_id = serializers.UUIDField(required=False)
    outcome = serializers.ChoiceField(
        choices=AuditEvent.Outcome.choices,
        required=False,
    )
    limit = serializers.IntegerField(
        required=False,
        default=50,
        min_value=1,
        max_value=100,
    )


class AuditEventSummarySerializer(serializers.ModelSerializer[AuditEvent]):
    """Serialize and validate audit event summary data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = AuditEvent
        fields = (
            "id",
            "occurred_at",
            "principal_kind",
            "principal_id",
            "event_edition_id",
            "capability_code",
            "operation",
            "target_type",
            "target_id",
            "outcome",
            "reason_code",
            "correlation_id",
            "source_channel",
            "delegated",
            "elevated",
            "break_glass",
        )
        read_only_fields = fields
