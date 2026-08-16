"""Closed request schemas for logistics catalog command APIs."""

from __future__ import annotations

from typing import Any, ClassVar, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from maru.core.openapi import CANONICAL_UUID_SCHEMA
from maru.core.serializers import StrictInputSerializer

from .models import (
    MAX_LOGISTICS_REASON_LENGTH,
    Asset,
    AssetAgreement,
    LogisticsEvent,
    LogisticsNode,
    LogisticsParty,
    RestrictedLogisticsAddress,
)
from .serializers import StrictDateTimeField
from .services import MAX_KIT_LINES, MAX_TRACKED_QUANTITY, MIN_QR_IDENTIFIER_LENGTH


@extend_schema_field(CANONICAL_UUID_SCHEMA)
class CanonicalUUIDField(serializers.UUIDField):
    """Accept only Maru's lower-case, hyphenated UUID representation."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a canonical lower-case hyphenated UUID."
    }

    def to_internal_value(self, data: object) -> UUID:
        value = super().to_internal_value(cast(Any, data))
        if not isinstance(data, str) or str(value) != data:
            self.fail("invalid")
        return value


class StrictIntegerField(serializers.IntegerField):
    """Accept a JSON integer without bool, string, or float coercion."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        **serializers.IntegerField.default_error_messages,
        "invalid_type": "Enter a JSON integer.",
    }

    def to_internal_value(self, data: object) -> int:
        if type(data) is not int:
            self.fail("invalid_type")
        return super().to_internal_value(data)


class SubjectLocatorSerializer(StrictInputSerializer):
    kind = serializers.ChoiceField(choices=LogisticsEvent.SubjectKind.choices)
    object_id = CanonicalUUIDField()

    class Meta:
        ref_name = "LogisticsCatalogSubjectLocator"


class OwnerSerializer(StrictInputSerializer):
    kind = serializers.ChoiceField(choices=Asset.OwnerKind.choices)
    account_id = CanonicalUUIDField(required=False, allow_null=True)
    party_id = CanonicalUUIDField(required=False, allow_null=True)


class ExternalActorSerializer(StrictInputSerializer):
    account_id = CanonicalUUIDField(required=False, allow_null=True)
    party_id = CanonicalUUIDField(required=False, allow_null=True)


class LogisticsCatalogCommandSerializer(StrictInputSerializer):
    reason = serializers.CharField(
        min_length=1,
        max_length=MAX_LOGISTICS_REASON_LENGTH,
    )


class LogisticsPartyProfileSerializer(StrictInputSerializer):
    kind = serializers.ChoiceField(choices=LogisticsParty.Kind.choices)
    role = serializers.ChoiceField(choices=LogisticsParty.Role.choices)
    legal_name = serializers.CharField(max_length=240)
    public_name = serializers.CharField(max_length=200)
    provider_reference = serializers.CharField(
        max_length=240, required=False, allow_blank=True
    )
    website_url = serializers.URLField(
        max_length=2_000,
        required=False,
        allow_blank=True,
    )


class LogisticsPartyCreateSerializer(LogisticsCatalogCommandSerializer):
    code = serializers.SlugField(max_length=96)
    profile = LogisticsPartyProfileSerializer()


class RestrictedAddressCreateSerializer(LogisticsCatalogCommandSerializer):
    purpose = serializers.ChoiceField(
        choices=RestrictedLogisticsAddress.Purpose.choices
    )
    subject_account_id = CanonicalUUIDField(required=False, allow_null=True)
    party_id = CanonicalUUIDField(required=False, allow_null=True)
    label = serializers.CharField(max_length=200)  # type: ignore[assignment]
    recipient_name = serializers.CharField(
        max_length=240, required=False, allow_blank=True
    )
    contact_email = serializers.EmailField(
        max_length=254,
        required=False,
        allow_blank=True,
    )
    contact_phone = serializers.RegexField(
        regex=r"^\+[1-9]\d{6,14}$", max_length=16, required=False, allow_blank=True
    )
    postal_address = serializers.CharField(max_length=1_000)
    access_instructions = serializers.CharField(
        max_length=5_000, required=False, allow_blank=True
    )
    retention_until = StrictDateTimeField(required=False, allow_null=True)


class LogisticsNodeCreateSerializer(LogisticsCatalogCommandSerializer):
    kind = serializers.ChoiceField(choices=LogisticsNode.Kind.choices)
    code = serializers.SlugField(max_length=96)
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(
        max_length=2_000, required=False, allow_blank=True
    )
    storage_address_id = CanonicalUUIDField(required=False, allow_null=True)
    external_owner_id = CanonicalUUIDField(required=False, allow_null=True)
    provider_id = CanonicalUUIDField(required=False, allow_null=True)
    vehicle_registration = serializers.CharField(
        max_length=40, required=False, allow_blank=True
    )
    venue_space_selection_id = CanonicalUUIDField(required=False, allow_null=True)
    capacity_note = serializers.CharField(
        max_length=500, required=False, allow_blank=True
    )


class SerializedAssetCreateSerializer(LogisticsCatalogCommandSerializer):
    catalog_code = serializers.SlugField(max_length=96)
    name = serializers.CharField(max_length=200)
    asset_type = serializers.CharField(max_length=120)
    manufacturer = serializers.CharField(
        max_length=160, required=False, allow_blank=True
    )
    model_name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    serial_number = serializers.CharField(
        max_length=200, required=False, allow_blank=True
    )
    acquisition = serializers.ChoiceField(choices=Asset.Acquisition.choices)
    value_class = serializers.CharField(max_length=32, required=False, allow_blank=True)
    owner = OwnerSerializer()


class StockLotCreateSerializer(LogisticsCatalogCommandSerializer):
    catalog_code = serializers.SlugField(max_length=96)
    name = serializers.CharField(max_length=200)
    stock_type = serializers.CharField(max_length=120)
    unit = serializers.CharField(max_length=40)
    initial_quantity = StrictIntegerField(
        min_value=1,
        max_value=MAX_TRACKED_QUANTITY,
    )
    value_class = serializers.CharField(max_length=32, required=False, allow_blank=True)
    owner = OwnerSerializer()


class PhysicalKeyCreateSerializer(LogisticsCatalogCommandSerializer):
    code = serializers.SlugField(max_length=96)
    label = serializers.CharField(max_length=200)  # type: ignore[assignment]
    opens_node_id = CanonicalUUIDField()
    provider_id = CanonicalUUIDField(required=False, allow_null=True)


class KeyholderAssignSerializer(LogisticsCatalogCommandSerializer):
    responsible_account_id = CanonicalUUIDField()
    starts_at = StrictDateTimeField()
    ends_at = StrictDateTimeField(required=False, allow_null=True)
    expected_version = StrictIntegerField(min_value=1)


class LogisticsLabelCreateSerializer(LogisticsCatalogCommandSerializer):
    subject = SubjectLocatorSerializer()
    label_code = serializers.CharField(max_length=96)
    qr_identifier = serializers.CharField(
        min_length=MIN_QR_IDENTIFIER_LENGTH,
        max_length=512,
        trim_whitespace=False,
    )


class AssetAgreementCreateSerializer(LogisticsCatalogCommandSerializer):
    subject = SubjectLocatorSerializer()
    kind = serializers.ChoiceField(choices=AssetAgreement.Kind.choices)
    provider = ExternalActorSerializer()
    borrower = ExternalActorSerializer(required=False)
    starts_at = StrictDateTimeField()
    ends_at = StrictDateTimeField()
    return_due_at = StrictDateTimeField()
    return_address_id = CanonicalUUIDField(required=False, allow_null=True)
    provider_reference = serializers.CharField(
        max_length=240, required=False, allow_blank=True
    )
    terms_reference = serializers.CharField(
        max_length=1_000, required=False, allow_blank=True
    )


class ReusableKitLineSerializer(StrictInputSerializer):
    subject = SubjectLocatorSerializer()
    quantity = StrictIntegerField(min_value=1, max_value=MAX_TRACKED_QUANTITY)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ReusableKitCreateSerializer(LogisticsCatalogCommandSerializer):
    code = serializers.SlugField(max_length=96)
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(
        max_length=2_000, required=False, allow_blank=True
    )
    lines: serializers.ListSerializer[dict[str, object]] = serializers.ListSerializer(
        child=ReusableKitLineSerializer(),
        allow_empty=False,
        max_length=MAX_KIT_LINES,
    )


class ManifestLineSerializer(StrictInputSerializer):
    subject = SubjectLocatorSerializer()
    quantity = StrictIntegerField(min_value=1, max_value=MAX_TRACKED_QUANTITY)
    packed_in_node_id = CanonicalUUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ManifestLineAddSerializer(LogisticsCatalogCommandSerializer):
    expected_version = StrictIntegerField(min_value=1)
    line = ManifestLineSerializer()


class ManifestReceiptSerializer(LogisticsCatalogCommandSerializer):
    expected_sequence = StrictIntegerField(min_value=0)
    occurred_at = StrictDateTimeField()
    condition_after = serializers.CharField(min_length=1, max_length=120)


__all__ = [
    "AssetAgreementCreateSerializer",
    "KeyholderAssignSerializer",
    "LogisticsLabelCreateSerializer",
    "LogisticsNodeCreateSerializer",
    "LogisticsPartyCreateSerializer",
    "ManifestLineAddSerializer",
    "ManifestReceiptSerializer",
    "PhysicalKeyCreateSerializer",
    "RestrictedAddressCreateSerializer",
    "ReusableKitCreateSerializer",
    "SerializedAssetCreateSerializer",
    "StockLotCreateSerializer",
]
