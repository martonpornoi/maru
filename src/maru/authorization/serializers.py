"""Human-readable Management Console access contracts."""

from typing import Any, cast

from rest_framework import serializers


class AccessCapabilitySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate access capability data."""

    code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    description = serializers.CharField()


class AccessGroupSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate access group data."""

    role_version_id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()
    version = serializers.IntegerField()
    description = serializers.CharField()
    capability_count = serializers.IntegerField()
    capabilities = AccessCapabilitySerializer(many=True)


class AccessAssignmentSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate access assignment data."""

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


class EffectiveAccessActionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate effective access action data."""

    capability_code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    allowed = serializers.BooleanField()
    permitted_fields = serializers.ListField(child=serializers.CharField())
    obligations = serializers.ListField(child=serializers.CharField())
    reason_code = serializers.CharField()
    source_category = serializers.CharField()
    source_label = serializers.CharField()


class EffectiveAccessSummarySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate effective access summary data."""

    scope_level = serializers.CharField()
    scope_label = serializers.CharField()
    can_manage_access = serializers.BooleanField()
    actions = EffectiveAccessActionSerializer(many=True)


class AccessWorkspaceSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate access workspace data."""

    organization_name = serializers.CharField()
    edition_name = serializers.CharField()
    can_revoke_assignments = serializers.BooleanField()
    effective_access = EffectiveAccessSummarySerializer()
    groups = AccessGroupSerializer(many=True)
    assignments = AccessAssignmentSerializer(many=True)


class AccessAssignmentCreateSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate access assignment create data."""

    person_email = serializers.EmailField(max_length=254)
    group_code = serializers.CharField(max_length=80)
    approver_email = serializers.EmailField(max_length=254)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=240, trim_whitespace=True)


class AccessAssignmentReplaceSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate access assignment replace data."""

    group_code = serializers.CharField(max_length=80)
    approver_email = serializers.EmailField(max_length=254)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=240, trim_whitespace=True)


class AccessAssignmentRevokeSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate access assignment revoke data."""

    reason = serializers.CharField(max_length=240, trim_whitespace=True)


class _ClosedPreviewInputSerializer(serializers.Serializer[dict[str, object]]):
    """Reject undeclared fields instead of silently discarding them."""

    def to_internal_value(self, data: Any) -> dict[str, object]:
        if not isinstance(data, dict):
            self.fail("invalid")
        unexpected = sorted(set(data) - set(self.fields))
        if unexpected:
            raise serializers.ValidationError(
                dict.fromkeys(unexpected, "Unexpected field.")
            )
        return cast("dict[str, object]", super().to_internal_value(data))


class AccessPreviewRequestSerializer(_ClosedPreviewInputSerializer):
    """Serialize and validate access preview request data."""

    mode = serializers.ChoiceField(choices=("person", "role"))
    person_email = serializers.EmailField(
        max_length=254,
        required=False,
        allow_blank=False,
    )
    role_version_id = serializers.UUIDField(required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Validate the supplied data.

        Parameters
        ----------
        attrs : dict[str, object]
            The attrs mapping to validate or transform.

        Returns
        -------
        dict[str, object]
            A mapping containing the resolved validate data.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        mode = attrs.get("mode")
        has_person = "person_email" in attrs
        has_role = "role_version_id" in attrs
        if mode == "person" and (not has_person or has_role):
            raise serializers.ValidationError(
                "Person preview requires only an exact person email."
            )
        if mode == "role" and (not has_role or has_person):
            raise serializers.ValidationError(
                "Role preview requires only one immutable role version."
            )
        return attrs


class AccessPreviewCapabilitySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate access preview capability data."""

    capability_code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    description = serializers.CharField()
    source_category = serializers.CharField()
    source_label = serializers.CharField()
    obligations = serializers.ListField(child=serializers.CharField())
    visible_fields = serializers.ListField(child=serializers.CharField())
    data_preview_available = serializers.BooleanField()
    disclosure_limited = serializers.BooleanField()


class AccessPreviewSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate access preview data."""

    mode = serializers.ChoiceField(choices=("person", "role"))
    subject_id = serializers.UUIDField()
    subject_label = serializers.CharField()
    scope_level = serializers.CharField()
    scope_label = serializers.CharField()
    evaluated_at = serializers.DateTimeField()
    capabilities = AccessPreviewCapabilitySerializer(many=True)
    disclosure_limited_count = serializers.IntegerField()
    session_unchanged = serializers.BooleanField()
    mutation_allowed = serializers.BooleanField()
