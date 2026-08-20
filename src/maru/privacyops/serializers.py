"""Provide serializers support for the privacyops module."""

from rest_framework import serializers

from maru.privacyops.models import (
    DisposalReceipt,
    PostEditionCorrection,
    SubjectRightsRequest,
)


class SubjectRightsRequestCreateSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate subject rights request create data."""

    organization_id = serializers.UUIDField(required=False, allow_null=True)
    kind = serializers.ChoiceField(choices=SubjectRightsRequest.Kind.choices)
    summary = serializers.CharField(max_length=1000)


class SubjectRightsRequestSerializer(serializers.ModelSerializer[SubjectRightsRequest]):
    """Serialize and validate subject rights request data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = SubjectRightsRequest
        fields = (
            "id",
            "organization_id",
            "kind",
            "status",
            "requested_at",
            "request_summary",
            "identity_verified_at",
            "completed_at",
            "safe_outcome_summary",
        )
        read_only_fields = fields


class StaffSubjectRightsRequestSerializer(
    serializers.ModelSerializer[SubjectRightsRequest]
):
    """Serialize and validate staff subject rights request data."""

    account_id = serializers.UUIDField(read_only=True)
    account_display_name = serializers.CharField(
        source="account.display_name",
        read_only=True,
    )
    account_email = serializers.EmailField(source="account.email", read_only=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        model = SubjectRightsRequest
        fields = (
            "id",
            "account_id",
            "account_display_name",
            "account_email",
            "organization_id",
            "kind",
            "status",
            "requested_at",
            "request_summary",
            "identity_verified_at",
            "completed_at",
            "safe_outcome_summary",
        )
        read_only_fields = fields


class SubjectRightsRequestTransitionSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate subject rights request transition data."""

    action = serializers.ChoiceField(
        choices=(
            ("begin_identity_check", "Begin identity check"),
            ("verify_identity", "Verify identity and begin work"),
            ("complete", "Complete"),
            ("deny", "Deny"),
        )
    )
    outcome_summary = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
    )


class PostEditionCorrectionCreateSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate post edition correction create data."""

    profile_id = serializers.UUIDField()
    changed_fields = serializers.JSONField()
    reason = serializers.CharField(max_length=1000)


class PostEditionCorrectionDecisionSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate post edition correction decision data."""

    approve = serializers.BooleanField()
    reason = serializers.CharField(max_length=1000)


class PostEditionCorrectionSerializer(
    serializers.ModelSerializer[PostEditionCorrection]
):
    """Serialize and validate post edition correction data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = PostEditionCorrection
        fields = (
            "id",
            "organization_id",
            "edition_id",
            "target_type",
            "target_id",
            "status",
            "changed_fields",
            "reason",
            "requested_at",
            "decided_at",
            "decision_reason",
        )
        read_only_fields = fields


class RegistrationProfileMinimizeSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate registration profile minimize data."""

    profile_id = serializers.UUIDField()
    policy_id = serializers.UUIDField()


class DisposalReceiptSerializer(serializers.ModelSerializer[DisposalReceipt]):
    """Serialize and validate disposal receipt data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = DisposalReceipt
        fields = (
            "id",
            "edition_id",
            "policy_id",
            "target_type",
            "target_id",
            "disposition",
            "applied_at",
            "safe_result_code",
            "downstream_receipts",
        )
        read_only_fields = fields
