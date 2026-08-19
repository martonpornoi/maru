"""Strict request and projection serializers for logistics APIs."""

import re
from typing import Any, ClassVar, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from maru.core.openapi import CANONICAL_UUID_SCHEMA
from maru.core.serializers import StrictInputSerializer

from .models import (
    MAX_LOGISTICS_REASON_LENGTH,
    MAX_OFFLINE_OPERATIONS,
    EquipmentOffer,
    EquipmentOfferItem,
    LogisticsEvent,
    LogisticsManifest,
)
from .queries import RESTRICTED_ACCESS_PURPOSES


@extend_schema_field(CANONICAL_UUID_SCHEMA)
class CanonicalUUIDField(serializers.UUIDField):
    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a canonical lower-case hyphenated UUID."
    }

    def to_internal_value(self, data: object) -> UUID:
        value = super().to_internal_value(cast(Any, data))
        if not isinstance(data, str) or str(value) != data:
            self.fail("invalid")
        return value


class StrictIntegerField(serializers.IntegerField):
    default_error_messages: ClassVar[dict[str, Any]] = {
        **serializers.IntegerField.default_error_messages,
        "invalid_type": "Enter a JSON integer.",
    }

    def to_internal_value(self, data: object) -> int:
        if type(data) is not int:
            self.fail("invalid_type")
        return super().to_internal_value(data)


_EXPLICIT_OFFSET = re.compile(r"(?:Z|[+-]\d{2}:\d{2})\Z")


class StrictDateTimeField(serializers.DateTimeField):
    """Accept one ISO date-time with an explicit UTC offset."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        **serializers.DateTimeField.default_error_messages,
        "explicit_offset": "Include an explicit UTC offset or Z suffix.",
    }

    def to_internal_value(self, value: object) -> Any:
        if not isinstance(value, str) or _EXPLICIT_OFFSET.search(value) is None:
            self.fail("explicit_offset")
        return super().to_internal_value(value)


class LogisticsCommandResultSerializer(serializers.Serializer[dict[str, object]]):
    object_id = serializers.UUIDField()
    receipt_id = serializers.UUIDField()
    resulting_version = serializers.IntegerField(min_value=1)
    replayed = serializers.BooleanField()


class LogisticsOfferItemProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    quantity = serializers.IntegerField(min_value=1)
    manufacturer = serializers.CharField()
    model_name = serializers.CharField()
    serial_number = serializers.CharField()
    condition = serializers.CharField()
    value_class = serializers.CharField()
    ownership_statement = serializers.CharField()


class LogisticsSelfOfferProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    title = serializers.CharField()
    description = serializers.CharField()
    available_from = serializers.DateTimeField()
    available_until = serializers.DateTimeField()
    requested_return_at = serializers.DateTimeField(allow_null=True)
    status = serializers.CharField()
    review_reason = serializers.CharField()
    aggregate_version = serializers.IntegerField(min_value=1)
    pickup_label = serializers.CharField()
    pickup_recipient_name = serializers.CharField()
    pickup_postal_address = serializers.CharField()
    pickup_access_instructions = serializers.CharField()
    pickup_retention_until = serializers.DateTimeField(allow_null=True)
    items = LogisticsOfferItemProjectionSerializer(many=True)


class LogisticsOfferQueueProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    offered_by_id = serializers.UUIDField()
    title = serializers.CharField()
    status = serializers.CharField()
    item_count = serializers.IntegerField(min_value=0)
    total_units = serializers.IntegerField(min_value=0)
    available_from = serializers.DateTimeField()
    available_until = serializers.DateTimeField()
    requested_return_at = serializers.DateTimeField(allow_null=True)
    responsible_department_id = serializers.UUIDField(allow_null=True)
    aggregate_version = serializers.IntegerField(min_value=1)


class LogisticsManifestLineProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    subject_kind = serializers.CharField()
    subject_id = serializers.UUIDField()
    label_snapshot = serializers.CharField()
    quantity = serializers.IntegerField(min_value=1)
    packed_in_node_id = serializers.UUIDField(allow_null=True)
    packed_in_label = serializers.CharField()
    notes = serializers.CharField()
    current_sequence = serializers.IntegerField(min_value=0)
    current_state = serializers.CharField()


class LogisticsManifestProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    manifest_number = serializers.CharField()
    kind = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField()
    responsible_department_id = serializers.UUIDField()
    source_node_id = serializers.UUIDField(allow_null=True)
    source_name = serializers.CharField()
    destination_node_id = serializers.UUIDField(allow_null=True)
    destination_name = serializers.CharField()
    vehicle_id = serializers.UUIDField(allow_null=True)
    vehicle_name = serializers.CharField()
    loading_starts_at = serializers.DateTimeField(allow_null=True)
    loading_ends_at = serializers.DateTimeField(allow_null=True)
    box_count = serializers.IntegerField(min_value=0)
    line_count = serializers.IntegerField(min_value=0)
    aggregate_version = serializers.IntegerField(min_value=1)
    lines = LogisticsManifestLineProjectionSerializer(many=True)


class LogisticsCurrentStateProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    subject_kind = serializers.CharField()
    subject_id = serializers.UUIDField()
    subject_label = serializers.CharField()
    current_node_id = serializers.UUIDField(allow_null=True)
    current_node_name = serializers.CharField()
    custodian_account_id = serializers.UUIDField(allow_null=True)
    custodian_party_id = serializers.UUIDField(allow_null=True)
    condition = serializers.CharField()
    quantity = serializers.IntegerField(min_value=0, allow_null=True)
    last_event_sequence = serializers.IntegerField(min_value=0)
    last_occurred_at = serializers.DateTimeField()


class LogisticsReturnProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    agreement_id = serializers.UUIDField()
    kind = serializers.CharField()
    subject_kind = serializers.CharField()
    subject_id = serializers.UUIDField()
    provider_kind = serializers.CharField()
    provider_id = serializers.UUIDField()
    return_due_at = serializers.DateTimeField()
    returned = serializers.BooleanField()
    overdue = serializers.BooleanField()


class LogisticsDiscrepancyProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    subject_kind = serializers.CharField()
    subject_id = serializers.UUIDField()
    expected_quantity = serializers.IntegerField(min_value=0, allow_null=True)
    observed_quantity = serializers.IntegerField(min_value=0, allow_null=True)
    description = serializers.CharField()
    status = serializers.CharField()
    aggregate_version = serializers.IntegerField(min_value=1)
    created_at = serializers.DateTimeField()


class LogisticsActivityProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    sequence = serializers.IntegerField(min_value=1)
    event_type = serializers.CharField()
    subject_kind = serializers.CharField()
    subject_id = serializers.UUIDField()
    source_node_id = serializers.UUIDField(allow_null=True)
    destination_node_id = serializers.UUIDField(allow_null=True)
    from_custodian_account_id = serializers.UUIDField(allow_null=True)
    to_custodian_account_id = serializers.UUIDField(allow_null=True)
    quantity = serializers.IntegerField(min_value=0, allow_null=True)
    condition_before = serializers.CharField()
    condition_after = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    actor_id = serializers.UUIDField()


class RestrictedLogisticsContactProjectionSerializer(
    serializers.Serializer[dict[str, Any]]
):
    address_id = serializers.UUIDField()
    purpose = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    recipient_name = serializers.CharField()
    contact_email = serializers.CharField()
    contact_phone = serializers.CharField()
    postal_address = serializers.CharField()
    access_instructions = serializers.CharField()
    retention_until = serializers.DateTimeField(allow_null=True)
    subject_account_id = serializers.UUIDField(allow_null=True)
    party_id = serializers.UUIDField(allow_null=True)


class NamedLogisticsChoiceSerializer(serializers.Serializer[dict[str, Any]]):
    value = serializers.UUIDField()
    label = serializers.CharField()  # type: ignore[assignment]


class NamedLogisticsCodeChoiceSerializer(serializers.Serializer[dict[str, Any]]):
    value = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]


class LogisticsFormChoicesSerializer(serializers.Serializer[dict[str, Any]]):
    departments = NamedLogisticsChoiceSerializer(many=True)
    parties = NamedLogisticsChoiceSerializer(many=True)
    addresses = NamedLogisticsChoiceSerializer(many=True)
    nodes = NamedLogisticsChoiceSerializer(many=True)
    packing_nodes = NamedLogisticsChoiceSerializer(many=True)
    vehicles = NamedLogisticsChoiceSerializer(many=True)
    venue_rooms = NamedLogisticsChoiceSerializer(many=True)
    venue_space_selections = NamedLogisticsChoiceSerializer(many=True)
    assets = NamedLogisticsChoiceSerializer(many=True)
    stock_lots = NamedLogisticsChoiceSerializer(many=True)
    physical_keys = NamedLogisticsChoiceSerializer(many=True)
    tracked_subjects = NamedLogisticsChoiceSerializer(many=True)
    people = NamedLogisticsChoiceSerializer(many=True)
    manifests = NamedLogisticsChoiceSerializer(many=True)
    labels = NamedLogisticsCodeChoiceSerializer(many=True)


class LogisticsWorkspaceProjectionSerializer(serializers.Serializer[dict[str, Any]]):
    offers = LogisticsOfferQueueProjectionSerializer(many=True)
    manifests = LogisticsManifestProjectionSerializer(many=True)
    current_states = LogisticsCurrentStateProjectionSerializer(many=True)
    due_returns = LogisticsReturnProjectionSerializer(many=True)
    discrepancies = LogisticsDiscrepancyProjectionSerializer(many=True)
    choices = LogisticsFormChoicesSerializer()


class OfferItemInputSerializer(StrictInputSerializer):
    kind = serializers.ChoiceField(choices=EquipmentOfferItem.Kind.choices)
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(
        max_length=2_000,
        allow_blank=True,
        required=False,
    )
    quantity = StrictIntegerField(min_value=1, max_value=1_000_000)
    manufacturer = serializers.CharField(
        max_length=160,
        allow_blank=True,
        required=False,
    )
    model_name = serializers.CharField(
        max_length=160,
        allow_blank=True,
        required=False,
    )
    serial_number = serializers.CharField(
        max_length=200,
        allow_blank=True,
        required=False,
    )
    condition = serializers.CharField(max_length=120)
    value_class = serializers.CharField(
        max_length=32,
        allow_blank=True,
        required=False,
    )
    ownership_statement = serializers.CharField(max_length=500)


class SelfOfferSubmitSerializer(StrictInputSerializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(
        max_length=5_000,
        allow_blank=True,
        required=False,
    )
    pickup_label = serializers.CharField(max_length=200)
    pickup_recipient_name = serializers.CharField(
        max_length=240,
        allow_blank=True,
        required=False,
    )
    pickup_postal_address = serializers.CharField(max_length=1_000)
    pickup_access_instructions = serializers.CharField(
        max_length=5_000,
        allow_blank=True,
        required=False,
    )
    pickup_retention_until = StrictDateTimeField()
    available_from = StrictDateTimeField()
    available_until = StrictDateTimeField()
    requested_return_at = StrictDateTimeField(required=False, allow_null=True)
    items: serializers.ListSerializer[dict[str, object]] = serializers.ListSerializer(
        child=OfferItemInputSerializer(),
        allow_empty=False,
        max_length=100,
    )
    reason = serializers.CharField(max_length=MAX_LOGISTICS_REASON_LENGTH)


class VersionedReasonSerializer(StrictInputSerializer):
    expected_version = StrictIntegerField(min_value=1)
    reason = serializers.CharField(max_length=MAX_LOGISTICS_REASON_LENGTH)


class OfferReviewSerializer(VersionedReasonSerializer):
    outcome = serializers.ChoiceField(
        choices=(
            EquipmentOffer.Status.ACCEPTED,
            EquipmentOffer.Status.REJECTED,
        )
    )
    responsible_department_id = CanonicalUUIDField(required=False, allow_null=True)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        outcome = attrs.get("outcome")
        department_supplied = "responsible_department_id" in self.initial_data
        department_id = attrs.get("responsible_department_id")
        if outcome == EquipmentOffer.Status.ACCEPTED and department_id is None:
            raise serializers.ValidationError(
                {
                    "responsible_department_id": [
                        "Provide the responsible Department when accepting an offer."
                    ]
                },
                code="responsible_department_required",
            )
        if outcome == EquipmentOffer.Status.REJECTED and department_supplied:
            raise serializers.ValidationError(
                {
                    "responsible_department_id": [
                        "Do not provide a Department when rejecting an offer."
                    ]
                },
                code="responsible_department_not_allowed",
            )
        return attrs


class OfferAcceptSerializer(VersionedReasonSerializer):
    outcome = serializers.ChoiceField(choices=(EquipmentOffer.Status.ACCEPTED,))
    responsible_department_id = CanonicalUUIDField()


class OfferRejectSerializer(VersionedReasonSerializer):
    outcome = serializers.ChoiceField(choices=(EquipmentOffer.Status.REJECTED,))


class SubjectLocatorSerializer(StrictInputSerializer):
    kind = serializers.ChoiceField(choices=LogisticsEvent.SubjectKind.choices)
    object_id = CanonicalUUIDField()

    class Meta:
        ref_name = "LogisticsMovementSubjectLocator"


class MovementSerializer(StrictInputSerializer):
    event_type = serializers.ChoiceField(choices=LogisticsEvent.EventType.choices)
    subject = SubjectLocatorSerializer()
    occurred_at = StrictDateTimeField()
    source_node_id = CanonicalUUIDField(required=False, allow_null=True)
    destination_node_id = CanonicalUUIDField(required=False, allow_null=True)
    to_custodian_account_id = CanonicalUUIDField(required=False, allow_null=True)
    to_custodian_party_id = CanonicalUUIDField(required=False, allow_null=True)
    quantity = StrictIntegerField(
        min_value=0,
        max_value=1_000_000_000,
        required=False,
        allow_null=True,
    )
    condition_before = serializers.CharField(
        max_length=120,
        allow_blank=True,
        required=False,
    )
    condition_after = serializers.CharField(
        max_length=120,
        allow_blank=True,
        required=False,
    )
    manifest_id = CanonicalUUIDField(required=False, allow_null=True)
    evidence_reference = serializers.CharField(
        max_length=1_000,
        allow_blank=True,
        required=False,
    )


class MovementCommandSerializer(StrictInputSerializer):
    movement = MovementSerializer()
    expected_sequence = StrictIntegerField(min_value=0)
    reason = serializers.CharField(max_length=MAX_LOGISTICS_REASON_LENGTH)


class ManifestLineInputSerializer(StrictInputSerializer):
    subject = SubjectLocatorSerializer()
    quantity = StrictIntegerField(min_value=1, max_value=1_000_000_000)
    packed_in_node_id = CanonicalUUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, allow_blank=True, required=False)


class ManifestCreateSerializer(StrictInputSerializer):
    responsible_department_id = CanonicalUUIDField()
    manifest_number = serializers.CharField(max_length=96)
    kind = serializers.ChoiceField(choices=LogisticsManifest.Kind.choices)
    title = serializers.CharField(max_length=200)
    source_node_id = CanonicalUUIDField(required=False, allow_null=True)
    destination_node_id = CanonicalUUIDField(required=False, allow_null=True)
    vehicle_id = CanonicalUUIDField(required=False, allow_null=True)
    provider_id = CanonicalUUIDField(required=False, allow_null=True)
    loading_starts_at = StrictDateTimeField(required=False, allow_null=True)
    loading_ends_at = StrictDateTimeField(required=False, allow_null=True)
    lines: serializers.ListSerializer[dict[str, object]] = serializers.ListSerializer(
        child=ManifestLineInputSerializer(),
        allow_empty=False,
        max_length=500,
    )
    reason = serializers.CharField(max_length=MAX_LOGISTICS_REASON_LENGTH)


class ManifestStateSerializer(VersionedReasonSerializer):
    action = serializers.ChoiceField(
        choices=("seal", "complete", "cancel_draft", "cancel_sealed")
    )


class OfflineOperationSerializer(StrictInputSerializer):
    sequence = StrictIntegerField(min_value=1, max_value=MAX_OFFLINE_OPERATIONS)
    idempotency_key = CanonicalUUIDField()
    expected_subject_sequence = StrictIntegerField(min_value=0)
    action = serializers.ChoiceField(choices=LogisticsEvent.EventType.choices)
    label_code = serializers.CharField(max_length=96)
    occurred_at = StrictDateTimeField()
    source_label_code = serializers.CharField(
        max_length=96,
        allow_blank=True,
        required=False,
    )
    destination_label_code = serializers.CharField(
        max_length=96,
        allow_blank=True,
        required=False,
    )
    quantity = StrictIntegerField(
        min_value=0,
        max_value=1_000_000_000,
        required=False,
        allow_null=True,
    )
    observed_condition = serializers.CharField(
        max_length=120,
        allow_blank=True,
        required=False,
    )

    class Meta:
        ref_name = "LogisticsOfflineOperation"


class OfflineBatchSerializer(StrictInputSerializer):
    device_code = serializers.CharField(max_length=96)
    snapshot_version = StrictIntegerField(min_value=0)
    policy_version = serializers.CharField(max_length=64)
    expires_at = StrictDateTimeField()
    operations: serializers.ListSerializer[dict[str, object]] = (
        serializers.ListSerializer(
            child=OfflineOperationSerializer(),
            allow_empty=False,
            max_length=MAX_OFFLINE_OPERATIONS,
        )
    )
    reason = serializers.CharField(max_length=MAX_LOGISTICS_REASON_LENGTH)


class RestrictedContactReadSerializer(StrictInputSerializer):
    purpose = serializers.ChoiceField(
        choices=("pickup", "storage", "return", "delivery", "provider")
    )
    access_purpose = serializers.ChoiceField(
        choices=tuple(sorted(RESTRICTED_ACCESS_PURPOSES))
    )
