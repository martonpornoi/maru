from rest_framework import serializers

from maru.accreditation.models import (
    Credential,
    OfflineCheckInOperation,
    OfflineCredentialManifest,
)


class CredentialSerializer(serializers.ModelSerializer[Credential]):
    class Meta:
        model = Credential
        fields = (
            "id",
            "registration_id",
            "public_id",
            "status",
            "issue_sequence",
            "label_snapshot",
            "issued_at",
            "revoked_at",
            "revocation_reason",
        )
        read_only_fields = fields


class CredentialCommandSerializer(serializers.Serializer[dict[str, object]]):
    reason = serializers.CharField(max_length=500)


class IssuedCredentialSerializer(serializers.Serializer[dict[str, object]]):
    credential = CredentialSerializer()
    credential_token = serializers.CharField(allow_null=True)


class OfflineManifestSerializer(serializers.ModelSerializer[OfflineCredentialManifest]):
    class Meta:
        model = OfflineCredentialManifest
        fields = (
            "id",
            "sequence",
            "valid_from",
            "valid_until",
            "generated_at",
            "credential_count",
            "payload",
            "payload_digest",
            "signature",
        )
        read_only_fields = fields


class OfflineCheckInSerializer(serializers.Serializer[dict[str, object]]):
    operation_id = serializers.UUIDField()
    device_sequence = serializers.IntegerField(min_value=1)
    manifest_sequence = serializers.IntegerField(min_value=1)
    credential_token = serializers.CharField(max_length=200)
    occurred_at = serializers.DateTimeField()
    signature = serializers.CharField(max_length=128)


class OfflineOperationSerializer(serializers.ModelSerializer[OfflineCheckInOperation]):
    class Meta:
        model = OfflineCheckInOperation
        fields = (
            "operation_id",
            "device_sequence",
            "manifest_sequence",
            "credential_public_id",
            "occurred_at",
            "received_at",
            "outcome",
            "safe_result_code",
        )
        read_only_fields = fields
