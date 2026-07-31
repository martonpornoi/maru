"""Human-readable Management Console access contracts."""

from rest_framework import serializers


class AccessCapabilitySerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    description = serializers.CharField()


class AccessGroupSerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    capability_count = serializers.IntegerField()
    capabilities = AccessCapabilitySerializer(many=True)


class AccessAssignmentSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    person_display_name = serializers.CharField()
    person_email = serializers.EmailField()
    group_code = serializers.CharField()
    group_name = serializers.CharField()
    scope_label = serializers.CharField()
    status = serializers.CharField()
    effective_from = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(allow_null=True)
    granted_by_name = serializers.CharField()
    approved_by_name = serializers.CharField()


class AccessWorkspaceSerializer(serializers.Serializer[dict[str, object]]):
    organization_name = serializers.CharField()
    edition_name = serializers.CharField()
    can_revoke_assignments = serializers.BooleanField()
    groups = AccessGroupSerializer(many=True)
    assignments = AccessAssignmentSerializer(many=True)


class AccessAssignmentCreateSerializer(serializers.Serializer[dict[str, object]]):
    person_email = serializers.EmailField(max_length=254)
    group_code = serializers.CharField(max_length=80)
    approver_email = serializers.EmailField(max_length=254)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=240, trim_whitespace=True)


class AccessAssignmentReplaceSerializer(serializers.Serializer[dict[str, object]]):
    group_code = serializers.CharField(max_length=80)
    approver_email = serializers.EmailField(max_length=254)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=240, trim_whitespace=True)


class AccessAssignmentRevokeSerializer(serializers.Serializer[dict[str, object]]):
    reason = serializers.CharField(max_length=240, trim_whitespace=True)
