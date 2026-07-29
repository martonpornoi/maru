"""Public commands and self-scoped identity projections."""

from rest_framework import serializers

from maru.identity.models import (
    AccountRestriction,
    AccountSecurityEvent,
    AccountSession,
    RestrictionAppeal,
)


class AccountSecurityEventSerializer(serializers.ModelSerializer[AccountSecurityEvent]):
    event_label = serializers.CharField(source="get_event_type_display")

    class Meta:
        model = AccountSecurityEvent
        fields = (
            "id",
            "event_type",
            "event_label",
            "outcome",
            "occurred_at",
            "source_channel",
            "detail_code",
        )
        read_only_fields = fields


class AccountBootstrapSerializer(serializers.Serializer[dict[str, str]]):
    email = serializers.EmailField()
    display_name = serializers.CharField(max_length=120)
    password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
    )


class SessionSignInSerializer(serializers.Serializer[dict[str, str]]):
    email = serializers.EmailField()
    password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
    )


class TokenSerializer(serializers.Serializer[dict[str, str]]):
    token = serializers.CharField(max_length=200, trim_whitespace=True)


class RecoveryRequestSerializer(serializers.Serializer[dict[str, str]]):
    email = serializers.EmailField()


class RecoveryCompleteSerializer(TokenSerializer):
    new_password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
    )


class StepUpSerializer(serializers.Serializer[dict[str, str]]):
    password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
    )


class AccountSessionSerializer(serializers.ModelSerializer[AccountSession]):
    active = serializers.BooleanField(source="is_active_session")

    class Meta:
        model = AccountSession
        fields = (
            "id",
            "label",
            "created_channel",
            "created_at",
            "last_seen_at",
            "step_up_verified_at",
            "active",
            "revoked_at",
            "revocation_reason",
        )
        read_only_fields = fields


class AccountRestrictionSerializer(serializers.ModelSerializer[AccountRestriction]):
    edition_id = serializers.UUIDField(allow_null=True)
    appeal_status = serializers.SerializerMethodField()

    class Meta:
        model = AccountRestriction
        fields = (
            "id",
            "organization_id",
            "edition_id",
            "kind",
            "status",
            "attendee_message",
            "effective_at",
            "expires_at",
            "revoked_at",
            "appeal_status",
        )
        read_only_fields = fields

    def get_appeal_status(self, obj: AccountRestriction) -> str | None:
        appeal = obj.appeals.order_by("-submitted_at", "-id").first()
        return appeal.status if appeal else None


class RestrictionAppealCreateSerializer(serializers.Serializer[dict[str, str]]):
    statement = serializers.CharField(max_length=4000)


class RestrictionAppealSerializer(serializers.ModelSerializer[RestrictionAppeal]):
    class Meta:
        model = RestrictionAppeal
        fields = (
            "id",
            "restriction_id",
            "statement",
            "status",
            "submitted_at",
            "decided_at",
            "decision_summary",
        )
        read_only_fields = fields


class StaffRestrictionCreateSerializer(serializers.Serializer[dict[str, object]]):
    account_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=AccountRestriction.Kind.choices)
    reason_code = serializers.SlugField(max_length=80)
    attendee_message = serializers.CharField(max_length=320)
    internal_reference = serializers.CharField(
        max_length=120,
        allow_blank=True,
        required=False,
    )
    effective_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(allow_null=True, required=False)
    notify_account = serializers.BooleanField(default=True)


class StaffRestrictionRevokeSerializer(serializers.Serializer[dict[str, str]]):
    reason = serializers.CharField(max_length=500)


class StaffRestrictionAppealDecisionSerializer(serializers.Serializer[dict[str, str]]):
    decision = serializers.ChoiceField(choices=("uphold", "revoke"))
    summary = serializers.CharField(max_length=500)
