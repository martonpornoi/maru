"""Explicit registration API projections and command inputs."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from maru.core.serializers import StrictInputSerializer
from maru.registration.finance import SUPPORTED_FINANCIAL_OPERATION_KINDS
from maru.registration.models import (
    AdmissionProduct,
    AdmissionTierReplacement,
    Entitlement,
    FinancialLedgerEntry,
    FinancialOperation,
    PaymentException,
    PaymentIntent,
    ReceiptRecord,
    Registration,
    RegistrationConfiguration,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationTemplate,
    RegistrationTimelineEntry,
    SettlementBatch,
)
from maru.registration.profile_choices import (
    LANGUAGE_CHOICES,
    MAX_BIO_LENGTH,
    MAX_FURSUITS,
    MAX_SPOKEN_LANGUAGES,
    OTHER_PRONOUN_CODE,
    PRONOUN_CHOICES,
)


class RegistrationSectionSerializer(serializers.ModelSerializer[RegistrationSection]):
    """Serialize and validate registration section data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = RegistrationSection
        fields = ("id", "key", "title", "description", "position")
        read_only_fields = fields


class RegistrationQuestionSerializer(serializers.ModelSerializer[RegistrationQuestion]):
    """Serialize and validate registration question data."""

    section = RegistrationSectionSerializer(allow_null=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        model = RegistrationQuestion
        fields = (
            "id",
            "section",
            "key",
            "label",
            "help_text",
            "field_type",
            "required",
            "position",
            "options",
            "purpose",
            "visibility",
            "classification",
            "condition_question_key",
            "condition_value",
        )
        read_only_fields = fields


class ProfileExtensionFieldSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate profile extension field data."""

    id = serializers.UUIDField()
    key = serializers.CharField()
    version = serializers.IntegerField()
    label = serializers.CharField()  # type: ignore[assignment]
    help_text = serializers.CharField(allow_blank=True)  # type: ignore[assignment]
    field_type = serializers.CharField()
    options = serializers.ListField(child=serializers.CharField())
    purpose = serializers.CharField()
    classification = serializers.CharField()
    audience_policy = serializers.CharField()
    audience_department_id = serializers.UUIDField(allow_null=True)
    required = serializers.BooleanField()  # type: ignore[assignment]
    writer_policy = serializers.CharField()
    can_write = serializers.BooleanField()
    current_value = serializers.JSONField(allow_null=True)
    current_sequence = serializers.IntegerField(min_value=0)
    updated_at = serializers.DateTimeField(allow_null=True)


class ProfileExtensionWorkspaceSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate profile extension workspace data."""

    registration_id = serializers.UUIDField()
    snapshot_digest = serializers.RegexField(r"^[0-9a-f]{64}$")
    fields = ProfileExtensionFieldSerializer(many=True)  # type: ignore[assignment]


class ProfileExtensionValueCommandResultSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Immutable resource created by one canonical value command."""

    registration_id = serializers.UUIDField()
    field_id = serializers.UUIDField()
    field_key = serializers.CharField()
    field_version = serializers.IntegerField(min_value=1)
    revision_id = serializers.UUIDField()
    receipt_id = serializers.UUIDField()
    result_sequence = serializers.IntegerField(min_value=1)
    value = serializers.JSONField()
    writer_kind = serializers.ChoiceField(choices=("owner", "staff"))
    source_channel = serializers.RegexField(r"^[a-z][a-z0-9_-]{0,31}$")
    changed_at = serializers.DateTimeField()


class WriteProfileExtensionValueSerializer(StrictInputSerializer):
    """Serialize and validate write profile extension value data."""

    field_id = serializers.UUIDField()
    value = serializers.JSONField(allow_null=True)
    expected_sequence = serializers.IntegerField(min_value=0, max_value=2_147_483_647)
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        trim_whitespace=True,
    )


class AdmissionProductSerializer(serializers.ModelSerializer[AdmissionProduct]):
    """Serialize and validate admission product data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = AdmissionProduct
        fields = (
            "id",
            "code",
            "name",
            "description",
            "price_minor",
            "capacity",
            "position",
            "entitlement_code",
            "entitlement_name",
            "status",
            "sales_open_at",
            "sales_close_at",
            "required_capacity_codes",
            "eligibility_explanation",
            "waitlist_enabled",
            "payment_window_minutes",
        )
        read_only_fields = fields


class RegistrationTemplateSummarySerializer(
    serializers.ModelSerializer[RegistrationTemplate]
):
    """Serialize and validate registration template summary data."""

    series_name = serializers.CharField(source="series.name", allow_null=True)
    question_count = serializers.IntegerField()
    product_count = serializers.IntegerField()

    class Meta:
        """Configure Django's declarative class metadata."""

        model = RegistrationTemplate
        fields = (
            "id",
            "code",
            "name",
            "description",
            "version",
            "status",
            "series_name",
            "published_at",
            "question_count",
            "product_count",
        )
        read_only_fields = fields


class RegistrationConfigurationSourceSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate registration configuration source data."""

    kind = serializers.ChoiceField(choices=("blank", "template", "edition"))
    id = serializers.UUIDField(allow_null=True)
    label = serializers.CharField()  # type: ignore[assignment]


class RegistrationConfigurationSerializer(
    serializers.ModelSerializer[RegistrationConfiguration]
):
    """Serialize and validate registration configuration data."""

    source_summary = serializers.SerializerMethodField()
    sections = RegistrationSectionSerializer(many=True)
    questions = RegistrationQuestionSerializer(many=True)
    products = AdmissionProductSerializer(many=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        model = RegistrationConfiguration
        fields = (
            "id",
            "name",
            "version",
            "status",
            "source_summary",
            "review_required",
            "review_note",
            "opens_at",
            "closes_at",
            "capacity",
            "currency",
            "minimum_age",
            "default_payment_window_minutes",
            "waitlist_enabled",
            "automatic_waitlist_promotion",
            "sections",
            "questions",
            "products",
        )
        read_only_fields = fields

    @extend_schema_field(RegistrationConfigurationSourceSerializer)
    def get_source_summary(
        self,
        obj: RegistrationConfiguration,
    ) -> dict[str, object]:
        """Return source summary.

        Parameters
        ----------
        obj : RegistrationConfiguration
            The model instance being validated or presented.

        Returns
        -------
        dict[str, object]
            A mapping containing the resolved get source summary data.
        """
        if obj.source_template_id is not None:
            return {
                "kind": "template",
                "id": obj.source_template_id,
                "label": str(obj.source_template),
            }
        if obj.source_edition_id is not None and obj.source_edition is not None:
            return {
                "kind": "edition",
                "id": obj.source_edition_id,
                "label": obj.source_edition.name,
            }
        return {"kind": "blank", "id": None, "label": "New configuration"}


class RegistrationSourceEditionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate registration source edition data."""

    edition_id = serializers.UUIDField()
    edition__name = serializers.CharField()
    latest_version = serializers.IntegerField()


class RegistrationTimelineSerializer(
    serializers.ModelSerializer[RegistrationTimelineEntry]
):
    """Serialize and validate registration timeline data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = RegistrationTimelineEntry
        fields = (
            "id",
            "sequence",
            "kind",
            "title",
            "summary",
            "occurred_at",
        )
        read_only_fields = fields


class EntitlementSerializer(serializers.ModelSerializer[Entitlement]):
    """Serialize and validate entitlement data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = Entitlement
        fields = ("code", "label_snapshot", "status", "granted_at")
        read_only_fields = fields


class SelfRegistrationSerializer(serializers.ModelSerializer[Registration]):
    """Serialize and validate self registration data."""

    product_name = serializers.CharField(source="product_name_snapshot")
    amount_minor = serializers.IntegerField(source="price_minor_snapshot")
    currency = serializers.CharField(source="currency_snapshot")
    entitlements = EntitlementSerializer(many=True)
    timeline = serializers.SerializerMethodField()

    class Meta:
        """Configure Django's declarative class metadata."""

        model = Registration
        fields = (
            "id",
            "reference",
            "state",
            "product_name",
            "amount_minor",
            "currency",
            "submitted_at",
            "waitlisted_at",
            "offered_at",
            "payment_due_at",
            "confirmed_at",
            "checked_in_at",
            "expired_at",
            "cancelled_at",
            "confirmation_basis",
            "entitlements",
            "timeline",
        )
        read_only_fields = fields

    @extend_schema_field(RegistrationTimelineSerializer(many=True))
    def get_timeline(self, obj: Registration) -> list[dict[str, object]]:
        """Return timeline.

        Parameters
        ----------
        obj : Registration
            The model instance being validated or presented.

        Returns
        -------
        list[dict[str, object]]
            The matching get timeline records in deterministic order.
        """
        entries = obj.timeline.filter(
            audience=RegistrationTimelineEntry.Audience.ATTENDEE_AND_STAFF
        )
        return list(RegistrationTimelineSerializer(entries, many=True).data)


class StaffRegistrationSerializer(serializers.ModelSerializer[Registration]):
    """Serialize and validate staff registration data."""

    account_id = serializers.UUIDField(source="account.id")
    submitted_by_id = serializers.UUIDField(allow_null=True)
    display_name = serializers.CharField(source="account.display_name")
    product_name = serializers.CharField(source="product_name_snapshot")
    amount_minor = serializers.IntegerField(source="price_minor_snapshot")
    currency = serializers.CharField(source="currency_snapshot")
    entitlements = EntitlementSerializer(many=True)
    timeline = RegistrationTimelineSerializer(many=True)

    class Meta:
        """Configure Django's declarative class metadata."""

        model = Registration
        fields = (
            "id",
            "reference",
            "account_id",
            "display_name",
            "state",
            "product_name",
            "amount_minor",
            "currency",
            "submitted_at",
            "waitlisted_at",
            "offered_at",
            "payment_due_at",
            "confirmed_at",
            "checked_in_at",
            "expired_at",
            "cancelled_at",
            "confirmation_basis",
            "submission_source",
            "submitted_by_id",
            "staff_submission_reason",
            "entitlements",
            "timeline",
        )
        read_only_fields = fields


class RegistrationConfigurationWorkspaceSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate registration configuration workspace data."""

    active_configuration = RegistrationConfigurationSerializer(allow_null=True)
    drafts = RegistrationConfigurationSerializer(many=True)
    templates = RegistrationTemplateSummarySerializer(many=True)
    source_editions = RegistrationSourceEditionSerializer(many=True)
    bootstrap_editor_path = serializers.CharField()


class AdmissionTierReplacementSerializer(
    serializers.ModelSerializer[AdmissionTierReplacement]
):
    """Serialize and validate admission tier replacement data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = AdmissionTierReplacement
        fields = (
            "id",
            "registration_id",
            "source_product_id",
            "target_product_id",
            "source_product_name_snapshot",
            "target_product_name_snapshot",
            "amount_due_minor",
            "currency",
            "status",
            "aggregate_version",
            "expected_registration_version",
            "resulting_registration_version",
            "reserved_at",
            "payment_due_at",
            "completed_at",
            "expired_at",
            "cancelled_at",
        )
        read_only_fields = fields


class MyRegistrationWorkspaceSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate my registration workspace data."""

    configuration = RegistrationConfigurationSerializer(allow_null=True)
    registration = SelfRegistrationSerializer(allow_null=True)
    tier_replacement = AdmissionTierReplacementSerializer(allow_null=True)
    demo_payment_enabled = serializers.BooleanField()
    server_time = serializers.DateTimeField()


class CreateConfigurationDraftSerializer(StrictInputSerializer):
    """Serialize and validate create configuration draft data."""

    name = serializers.CharField(max_length=160)
    reason = serializers.CharField(max_length=500)
    source_template_id = serializers.UUIDField(required=False)
    source_edition_id = serializers.UUIDField(required=False)
    opens_at = serializers.DateTimeField(required=False)
    closes_at = serializers.DateTimeField(required=False)
    capacity = serializers.IntegerField(required=False, min_value=1)
    currency = serializers.CharField(required=False, min_length=3, max_length=3)
    minimum_age = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=120,
    )
    default_payment_window_minutes = serializers.IntegerField(
        required=False,
        min_value=15,
        max_value=43_200,
    )
    waitlist_enabled = serializers.BooleanField(required=False)
    automatic_waitlist_promotion = serializers.BooleanField(required=False)

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
        if attrs.get("source_template_id") and attrs.get("source_edition_id"):
            raise serializers.ValidationError(
                "Choose either a template or an edition source."
            )
        has_source = bool(
            attrs.get("source_template_id") or attrs.get("source_edition_id")
        )
        blank_required = {"opens_at", "closes_at", "capacity", "currency"}
        if not has_source and not blank_required <= set(attrs):
            raise serializers.ValidationError(
                "A blank draft needs opening, closing, capacity, and currency."
            )
        return attrs


class ActivateConfigurationSerializer(StrictInputSerializer):
    """Serialize and validate activate configuration data."""

    configuration_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=500)


class PublishTemplateSerializer(StrictInputSerializer):
    """Serialize and validate publish template data."""

    configuration_id = serializers.UUIDField()
    code = serializers.SlugField(max_length=80)
    name = serializers.CharField(max_length=160)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2_000,
    )
    series_limited = serializers.BooleanField(default=True)
    reason = serializers.CharField(max_length=500)


class SubmitRegistrationSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate submit registration data."""

    product_id = serializers.UUIDField()
    answers = serializers.JSONField()


class HeadlessFursuitSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate headless fursuit data."""

    name = serializers.CharField(max_length=120)
    species = serializers.CharField(required=False, allow_blank=True, max_length=120)
    reuse_from_id = serializers.UUIDField(required=False, allow_null=True)


class GuardianDetailsSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate guardian details data."""

    name = serializers.CharField(max_length=200)
    email = serializers.EmailField()
    relationship = serializers.CharField(max_length=80)
    notice_version = serializers.CharField(max_length=40)


class HeadlessProfileSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate headless profile data."""

    real_name = serializers.CharField(max_length=200)
    date_of_birth = serializers.DateField()
    address_line_1 = serializers.CharField(max_length=200)
    address_line_2 = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
    )
    locality = serializers.CharField(max_length=120)
    postal_code = serializers.CharField(max_length=32)
    region = serializers.CharField(max_length=120)
    country_code = serializers.RegexField(r"^[A-Za-z]{2}$", max_length=2)
    emergency_contact_name = serializers.CharField(max_length=200)
    emergency_contact_phone = serializers.RegexField(
        r"^[0-9+().\-\s]{7,40}$",
        max_length=40,
    )
    phone_number = serializers.RegexField(
        r"^[0-9+().\-\s]{7,40}$",
        max_length=40,
    )
    telegram_handle = serializers.RegexField(
        r"^@?[A-Za-z0-9_]{5,32}$",
        required=False,
        allow_blank=True,
        max_length=64,
    )
    pronoun_code = serializers.ChoiceField(choices=PRONOUN_CHOICES)
    other_pronouns = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=80,
    )
    bio = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_BIO_LENGTH,
    )
    spoken_language_codes = serializers.ListField(
        child=serializers.ChoiceField(choices=LANGUAGE_CHOICES),
        max_length=MAX_SPOKEN_LANGUAGES,
    )
    brings_fursuits = serializers.BooleanField()
    reuse_profile_photo_id = serializers.UUIDField(
        required=False,
        allow_null=True,
    )
    fursuits = HeadlessFursuitSerializer(many=True, required=False)
    directory_visible = serializers.BooleanField(default=False)
    directory_country_code = serializers.RegexField(
        r"^[A-Za-z]{2}$",
        required=False,
        allow_blank=True,
        max_length=2,
    )
    guardian = GuardianDetailsSerializer(required=False)

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
        fursuits = attrs.get("fursuits", [])
        if isinstance(fursuits, list) and len(fursuits) > MAX_FURSUITS:
            raise serializers.ValidationError(
                {
                    "fursuits": (
                        f"A profile may include no more than {MAX_FURSUITS} fursuits."
                    )
                }
            )
        if bool(attrs.get("brings_fursuits")) != bool(fursuits):
            raise serializers.ValidationError(
                {"fursuits": "Fursuit entries must match the bring-fursuits choice."}
            )
        pronoun_code = attrs.get("pronoun_code")
        other_pronouns = str(attrs.get("other_pronouns", "")).strip()
        if pronoun_code == OTHER_PRONOUN_CODE and not other_pronouns:
            raise serializers.ValidationError(
                {"other_pronouns": "Enter the pronouns you want displayed."}
            )
        if pronoun_code != OTHER_PRONOUN_CODE:
            attrs["other_pronouns"] = ""
        codes = attrs.get("spoken_language_codes", [])
        if isinstance(codes, list) and len(set(codes)) != len(codes):
            raise serializers.ValidationError(
                {"spoken_language_codes": "Choose each language only once."}
            )
        directory_country_code = str(attrs.get("directory_country_code", "")).upper()
        if directory_country_code and not attrs.get("directory_visible"):
            raise serializers.ValidationError(
                {
                    "directory_country_code": (
                        "Join the public attendee list before adding a public country."
                    )
                }
            )
        attrs["directory_country_code"] = directory_country_code
        return attrs


class HeadlessRegistrationSubmissionSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate headless registration submission data."""

    idempotency_key = serializers.UUIDField()
    configuration_version = serializers.IntegerField(min_value=1)
    product_id = serializers.UUIDField()
    answers = serializers.JSONField()
    profile = HeadlessProfileSerializer()
    collection_notice_version = serializers.CharField(max_length=40)
    directory_consent_version = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=40,
    )


class GuardianConsentAcceptSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate guardian consent accept data."""

    token = serializers.CharField(max_length=200)
    guardian_name = serializers.CharField(max_length=200)


class DemoPaymentSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate demo payment data."""

    idempotency_key = serializers.UUIDField()


class CreatePaymentIntentSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate create payment intent data."""

    provider_account_id = serializers.UUIDField()
    idempotency_key = serializers.UUIDField()
    return_url = serializers.URLField(max_length=500)


class PaymentIntentSerializer(serializers.ModelSerializer[PaymentIntent]):
    """Serialize and validate payment intent data."""

    provider_name = serializers.CharField(source="provider_account.display_name")

    class Meta:
        """Configure Django's declarative class metadata."""

        model = PaymentIntent
        fields = (
            "id",
            "registration_id",
            "tier_replacement_id",
            "provider_name",
            "amount_minor",
            "currency",
            "status",
            "checkout_url",
            "expires_at",
            "safe_result_code",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ReserveAdmissionTierReplacementSerializer(StrictInputSerializer):
    """Serialize and validate reserve admission tier replacement data."""

    target_product_id = serializers.UUIDField()
    expected_registration_version = serializers.IntegerField(min_value=1)


class RegistrationCapacityAdjustmentCommandSerializer(StrictInputSerializer):
    """Serialize and validate registration capacity adjustment command data."""

    product_id = serializers.UUIDField(required=False, allow_null=True)
    new_capacity = serializers.IntegerField(min_value=1, max_value=1_000_000)
    expected_control_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=500)


class RegistrationCapacityAdjustmentResultSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate registration capacity adjustment result data."""

    id = serializers.UUIDField()
    scope = serializers.ChoiceField(choices=("overall", "product"))
    product_id = serializers.UUIDField(allow_null=True)
    previous_capacity = serializers.IntegerField()
    new_capacity = serializers.IntegerField()
    hard_ceiling = serializers.IntegerField()
    control_version = serializers.IntegerField()
    occurred_at = serializers.DateTimeField()


class WaitlistBatchOfferCommandSerializer(StrictInputSerializer):
    """Serialize and validate waitlist batch offer command data."""

    product_id = serializers.UUIDField()
    batch_size = serializers.IntegerField(min_value=1, max_value=100)
    expected_control_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=500)


class WaitlistBatchOfferResultSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate waitlist batch offer result data."""

    id = serializers.UUIDField()
    product_id = serializers.UUIDField()
    requested_size = serializers.IntegerField()
    offered_count = serializers.IntegerField()
    offered_registration_ids = serializers.ListField(child=serializers.UUIDField())
    control_version = serializers.IntegerField()
    occurred_at = serializers.DateTimeField()


class RegistrationCommerceActivitySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate registration commerce activity data."""

    event_name = serializers.CharField()
    action = serializers.CharField()
    actor_label = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    target_count = serializers.IntegerField()


class RegistrationCommerceCapacitySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate registration commerce capacity data."""

    product_id = serializers.UUIDField(allow_null=True)
    product_name = serializers.CharField(allow_blank=True)
    configured_capacity = serializers.IntegerField()
    effective_capacity = serializers.IntegerField()
    hard_ceiling = serializers.IntegerField()
    occupied = serializers.IntegerField()
    pending_target_holds = serializers.IntegerField()
    waitlisted = serializers.IntegerField()


class RegistrationCommerceWorkspaceSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate registration commerce workspace data."""

    control_version = serializers.IntegerField()
    capacities = RegistrationCommerceCapacitySerializer(many=True)
    activity = RegistrationCommerceActivitySerializer(many=True)


class PaymentExceptionSerializer(serializers.ModelSerializer[PaymentException]):
    """Serialize and validate payment exception data."""

    provider_name = serializers.CharField(source="provider_account.display_name")

    class Meta:
        """Configure Django's declarative class metadata."""

        model = PaymentException
        fields = (
            "id",
            "edition_id",
            "provider_name",
            "payment_intent_id",
            "kind",
            "status",
            "safe_summary",
            "opened_at",
            "resolved_at",
            "resolution_reason",
        )
        read_only_fields = fields


class ResolvePaymentExceptionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate resolve payment exception data."""

    reason = serializers.CharField(max_length=500)


class ProposeFinancialOperationSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate propose financial operation data."""

    kind = serializers.ChoiceField(
        choices=tuple(
            (kind, FinancialOperation.Kind(kind).label)
            for kind in SUPPORTED_FINANCIAL_OPERATION_KINDS
        )
    )
    amount_minor = serializers.IntegerField(min_value=0, default=0)
    target_account_id = serializers.UUIDField(required=False, allow_null=True)
    target_product_id = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=500)


class ApproveFinancialOperationSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate approve financial operation data."""

    reason = serializers.CharField(max_length=500)


class FinancialOperationSerializer(serializers.ModelSerializer[FinancialOperation]):
    """Serialize and validate financial operation data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = FinancialOperation
        fields = (
            "id",
            "registration_id",
            "kind",
            "status",
            "amount_minor",
            "currency",
            "target_account_id",
            "target_product_id",
            "requested_by_id",
            "requested_at",
            "request_reason",
            "approved_by_id",
            "approved_at",
            "approval_reason",
            "completed_at",
            "safe_result_code",
        )
        read_only_fields = fields


class FinancialLedgerEntrySerializer(serializers.ModelSerializer[FinancialLedgerEntry]):
    """Serialize and validate financial ledger entry data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = FinancialLedgerEntry
        fields = (
            "id",
            "registration_id",
            "operation_id",
            "kind",
            "direction",
            "amount_minor",
            "currency",
            "occurred_at",
            "provider_reference",
            "settlement_reference",
            "safe_description",
        )
        read_only_fields = fields


class ReceiptRecordSerializer(serializers.ModelSerializer[ReceiptRecord]):
    """Serialize and validate receipt record data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = ReceiptRecord
        fields = (
            "id",
            "registration_id",
            "kind",
            "document_number",
            "issued_at",
            "amount_minor",
            "currency",
            "description_snapshot",
        )
        read_only_fields = fields


class ReconcileSettlementSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate reconcile settlement data."""

    provider_account_id = serializers.UUIDField()
    provider_reference = serializers.CharField(max_length=160)
    currency = serializers.CharField(min_length=3, max_length=3)
    gross_minor = serializers.IntegerField(min_value=0)
    fee_minor = serializers.IntegerField(min_value=0)
    refund_minor = serializers.IntegerField(min_value=0)
    dispute_minor = serializers.IntegerField(min_value=0)
    net_minor = serializers.IntegerField()
    settled_at = serializers.DateTimeField()
    ledger_entry_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=5000,
    )
    reason = serializers.CharField(max_length=500)


class SettlementBatchSerializer(serializers.ModelSerializer[SettlementBatch]):
    """Serialize and validate settlement batch data."""

    class Meta:
        """Configure Django's declarative class metadata."""

        model = SettlementBatch
        fields = (
            "id",
            "provider_account_id",
            "provider_reference",
            "currency",
            "gross_minor",
            "fee_minor",
            "refund_minor",
            "dispute_minor",
            "net_minor",
            "settled_at",
            "status",
            "reconciled_at",
            "safe_result_code",
        )
        read_only_fields = fields


class CheckInSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate check in data."""

    reason = serializers.CharField(max_length=500)


class ChangePaymentDeadlineSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate change payment deadline data."""

    new_deadline = serializers.DateTimeField()
    reason = serializers.CharField(max_length=500)


class WaivePaymentSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate waive payment data."""

    reason = serializers.CharField(max_length=500)


class PublicProductAvailabilitySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public product availability data."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    price_minor = serializers.IntegerField()
    currency = serializers.CharField()
    sales_open_at = serializers.DateTimeField(allow_null=True)
    sales_close_at = serializers.DateTimeField(allow_null=True)
    selectable = serializers.BooleanField()
    availability_code = serializers.CharField()
    availability_explanation = serializers.CharField()
    waitlist = serializers.BooleanField()


class PublicCodeLabelSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public code label data."""

    code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]


class PublicProfileContractSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public profile contract data."""

    snapshot_scope = serializers.CharField()
    suggestion_mode = serializers.CharField()
    pronoun_choices = PublicCodeLabelSerializer(many=True)
    other_pronoun_code = serializers.CharField()
    bio_max_length = serializers.IntegerField()
    language_standard = serializers.CharField()
    language_choices = PublicCodeLabelSerializer(many=True)
    spoken_language_limit = serializers.IntegerField()
    fursuit_limit = serializers.IntegerField()
    multiple_fursuits = serializers.BooleanField()
    new_media_review_status = serializers.CharField()
    approved_media_reusable = serializers.BooleanField()
    public_attendee_list_requires_consent = serializers.BooleanField()
    public_attendee_list_requires_confirmation = serializers.BooleanField()
    public_attendee_country_is_optional = serializers.BooleanField()
    public_attendee_labels_are_authoritative = serializers.BooleanField()
    guardian_consent_supported = serializers.BooleanField()
    guardian_age_threshold = serializers.IntegerField(allow_null=True)
    guardian_notice_version = serializers.CharField(allow_blank=True)


class PublicClientContractSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public client contract data."""

    api_version = serializers.CharField()
    csrf_api = serializers.CharField()
    account_bootstrap_api = serializers.CharField()
    session_api = serializers.CharField()
    submission_api = serializers.CharField()
    authentication = serializers.CharField()
    browser_origin_policy = serializers.CharField()
    payment_return_is_proof = serializers.BooleanField()


class PublicRegistrationDefinitionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public registration definition data."""

    edition_id = serializers.UUIDField()
    organization_name = serializers.CharField()
    series_name = serializers.CharField()
    edition_name = serializers.CharField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    time_zone = serializers.CharField()
    configuration_version = serializers.IntegerField()
    opens_at = serializers.DateTimeField()
    closes_at = serializers.DateTimeField()
    minimum_age = serializers.IntegerField()
    default_payment_window_minutes = serializers.IntegerField()
    waitlist_enabled = serializers.BooleanField()
    client_contract = PublicClientContractSerializer()
    profile_contract = PublicProfileContractSerializer()
    sections = RegistrationSectionSerializer(many=True)
    questions = RegistrationQuestionSerializer(many=True)
    products = PublicProductAvailabilitySerializer(many=True)


class PublicRegistrationEditionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public registration edition data."""

    edition_id = serializers.UUIDField()
    organization_name = serializers.CharField()
    series_name = serializers.CharField()
    edition_name = serializers.CharField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    time_zone = serializers.CharField()
    registration_api_path = serializers.CharField()
    registration_web_path = serializers.CharField()
    attendee_api_path = serializers.CharField()
    attendee_web_path = serializers.CharField()


class PublicAttendeeFursuitSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public attendee fursuit data."""

    name = serializers.CharField()
    species = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class AttendanceLabelSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate attendance label data."""

    code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    tone = serializers.CharField()


class PublicAttendeeSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate public attendee data."""

    display_name = serializers.CharField()
    pronouns = serializers.CharField()
    bio = serializers.CharField()
    spoken_languages = PublicCodeLabelSerializer(many=True)
    profile_photo_url = serializers.CharField(allow_null=True)
    country_code = serializers.CharField(allow_blank=True)
    attendance_labels = AttendanceLabelSerializer(many=True)
    fursuits = PublicAttendeeFursuitSerializer(many=True)


class SelfProfileSuggestionFursuitSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate self profile suggestion fursuit data."""

    reuse_from_id = serializers.UUIDField(allow_null=True)
    name = serializers.CharField()
    species = serializers.CharField()
    photo_review_status = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class SelfProfileSuggestionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate self profile suggestion data."""

    source_profile_id = serializers.UUIDField()
    source_edition_id = serializers.UUIDField()
    source_edition_name = serializers.CharField()
    notice = serializers.CharField()
    real_name = serializers.CharField()
    date_of_birth = serializers.DateField()
    address_line_1 = serializers.CharField()
    address_line_2 = serializers.CharField()
    locality = serializers.CharField()
    postal_code = serializers.CharField()
    region = serializers.CharField()
    country_code = serializers.CharField()
    emergency_contact_name = serializers.CharField()
    emergency_contact_phone = serializers.CharField()
    phone_number = serializers.CharField()
    telegram_handle = serializers.CharField()
    pronoun_code = serializers.CharField()
    other_pronouns = serializers.CharField()
    bio = serializers.CharField()
    spoken_language_codes = serializers.ListField(child=serializers.CharField())
    brings_fursuits = serializers.BooleanField()
    reuse_profile_photo_id = serializers.UUIDField(allow_null=True)
    profile_photo_review_status = serializers.CharField()
    profile_photo_url = serializers.CharField(allow_null=True)
    fursuits = SelfProfileSuggestionFursuitSerializer(many=True)
    directory_visible = serializers.BooleanField()
    directory_country_code = serializers.CharField(allow_blank=True)


class SelfAttendeeFursuitSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate self attendee fursuit data."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    species = serializers.CharField()
    photo_review_status = serializers.CharField()
    photo_review_note = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


class SelfAttendeeProfileSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate self attendee profile data."""

    id = serializers.UUIDField()
    edition_id = serializers.UUIDField()
    editable = serializers.BooleanField()
    real_name = serializers.CharField()
    date_of_birth = serializers.DateField()
    address_line_1 = serializers.CharField()
    address_line_2 = serializers.CharField()
    locality = serializers.CharField()
    postal_code = serializers.CharField()
    region = serializers.CharField()
    country_code = serializers.CharField()
    emergency_contact_name = serializers.CharField()
    emergency_contact_phone = serializers.CharField()
    phone_number = serializers.CharField()
    telegram_handle = serializers.CharField()
    pronoun_code = serializers.CharField()
    other_pronouns = serializers.CharField()
    pronouns = serializers.CharField()
    bio = serializers.CharField()
    spoken_language_codes = serializers.ListField(child=serializers.CharField())
    brings_fursuits = serializers.BooleanField()
    profile_photo_review_status = serializers.CharField()
    profile_photo_review_note = serializers.CharField()
    profile_photo_url = serializers.CharField(allow_null=True)
    fursuits = SelfAttendeeFursuitSerializer(many=True)
    directory_visible = serializers.BooleanField()
    directory_country_code = serializers.CharField(allow_blank=True)


class SelfAttendeeFursuitUpdateSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate self attendee fursuit update data."""

    id = serializers.UUIDField(required=False)
    reuse_from_id = serializers.UUIDField(required=False)
    name = serializers.CharField(max_length=120)
    species = serializers.CharField(required=False, allow_blank=True, max_length=120)
    keep_photo = serializers.BooleanField(default=True)


class UpdateSelfAttendeeProfileSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate update self attendee profile data."""

    real_name = serializers.CharField(max_length=200)
    date_of_birth = serializers.DateField()
    address_line_1 = serializers.CharField(max_length=200)
    address_line_2 = serializers.CharField(allow_blank=True, max_length=200)
    locality = serializers.CharField(max_length=120)
    postal_code = serializers.CharField(max_length=32)
    region = serializers.CharField(max_length=120)
    country_code = serializers.RegexField(r"^[A-Za-z]{2}$", max_length=2)
    emergency_contact_name = serializers.CharField(max_length=200)
    emergency_contact_phone = serializers.RegexField(
        r"^[0-9+().\-\s]{7,40}$",
        max_length=40,
    )
    phone_number = serializers.RegexField(
        r"^[0-9+().\-\s]{7,40}$",
        max_length=40,
    )
    telegram_handle = serializers.RegexField(
        r"^@?[A-Za-z0-9_]{5,32}$",
        required=False,
        allow_blank=True,
        max_length=64,
    )
    pronoun_code = serializers.ChoiceField(choices=PRONOUN_CHOICES)
    other_pronouns = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=80,
    )
    bio = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_BIO_LENGTH,
    )
    spoken_language_codes = serializers.ListField(
        child=serializers.ChoiceField(choices=LANGUAGE_CHOICES),
        max_length=MAX_SPOKEN_LANGUAGES,
    )
    brings_fursuits = serializers.BooleanField()
    profile_photo_action = serializers.ChoiceField(
        choices=("keep", "remove", "reuse"),
        default="keep",
    )
    reuse_profile_photo_id = serializers.UUIDField(required=False)
    fursuits = SelfAttendeeFursuitUpdateSerializer(many=True)
    directory_visible = serializers.BooleanField()
    directory_country_code = serializers.RegexField(
        r"^[A-Za-z]{2}$",
        required=False,
        allow_blank=True,
        max_length=2,
    )

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
        action = attrs.get("profile_photo_action")
        reuse_id = attrs.get("reuse_profile_photo_id")
        if action == "reuse" and reuse_id is None:
            raise serializers.ValidationError(
                {"reuse_profile_photo_id": "Choose an approved image to reuse."}
            )
        if action != "reuse" and reuse_id is not None:
            raise serializers.ValidationError(
                {
                    "reuse_profile_photo_id": (
                        "Only provide a reuse id with the reuse action."
                    )
                }
            )
        fursuits = attrs.get("fursuits", [])
        if isinstance(fursuits, list) and len(fursuits) > MAX_FURSUITS:
            raise serializers.ValidationError(
                {
                    "fursuits": (
                        f"A profile may include no more than {MAX_FURSUITS} fursuits."
                    )
                }
            )
        if bool(attrs.get("brings_fursuits")) != bool(fursuits):
            raise serializers.ValidationError(
                {"fursuits": "Fursuit entries must match the bring-fursuits choice."}
            )
        pronoun_code = attrs.get("pronoun_code")
        other_pronouns = str(attrs.get("other_pronouns", "")).strip()
        if pronoun_code == OTHER_PRONOUN_CODE and not other_pronouns:
            raise serializers.ValidationError(
                {"other_pronouns": "Enter the pronouns you want displayed."}
            )
        if pronoun_code != OTHER_PRONOUN_CODE:
            attrs["other_pronouns"] = ""
        directory_country_code = str(attrs.get("directory_country_code", "")).upper()
        if directory_country_code and not attrs.get("directory_visible"):
            raise serializers.ValidationError(
                {
                    "directory_country_code": (
                        "Join the public attendee list before adding a public country."
                    )
                }
            )
        attrs["directory_country_code"] = directory_country_code
        return attrs


class SelfProfileImageUploadSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate self profile image upload data."""

    image = serializers.FileField()

    def validate_image(self, image: object) -> object:
        """Validate image.

        Parameters
        ----------
        image : object
            The image used to validate or render the API representation.

        Returns
        -------
        object
            The normalized value for validate image.

        Raises
        ------
        serializers.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        from maru.registration.profile_policy import (  # noqa: PLC0415
            ALLOWED_FURSUIT_PHOTO_CONTENT_TYPES,
            MAX_FURSUIT_PHOTO_BYTES,
        )

        if image.size > MAX_FURSUIT_PHOTO_BYTES:  # type: ignore[attr-defined]
            raise serializers.ValidationError("Use an image no larger than 5 MB.")
        if image.content_type not in ALLOWED_FURSUIT_PHOTO_CONTENT_TYPES:  # type: ignore[attr-defined]
            raise serializers.ValidationError("Upload a JPEG, PNG, or WebP image.")
        return image


class ProfileMediaReviewItemSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate profile media review item data."""

    id = serializers.UUIDField()
    profile_id = serializers.UUIDField()
    account_id = serializers.UUIDField()
    display_name = serializers.CharField()
    media_kind = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    review_status = serializers.CharField()
    preview_path = serializers.CharField()
    submitted_at = serializers.DateTimeField()


class ProfileMediaReviewDecisionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate profile media review decision data."""

    media_kind = serializers.ChoiceField(choices=("profile_photo", "fursuit_photo"))
    decision = serializers.ChoiceField(choices=("approved", "rejected"))
    reason = serializers.CharField(max_length=500)


class RegistrationReconciliationProductSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate registration reconciliation product data."""

    product_name = serializers.CharField()
    currency = serializers.CharField()
    registrations = serializers.IntegerField()
    waitlisted = serializers.IntegerField()
    payment_pending = serializers.IntegerField()
    provider_paid = serializers.IntegerField()
    provider_paid_minor = serializers.IntegerField()
    waived = serializers.IntegerField()
    waived_minor = serializers.IntegerField()
    free_confirmed = serializers.IntegerField()
    expired = serializers.IntegerField()
    cancelled = serializers.IntegerField()


class RegistrationReconciliationSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate registration reconciliation data."""

    generated_at = serializers.DateTimeField()
    products = RegistrationReconciliationProductSerializer(many=True)


class AttendeeCountryBreakdownSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate attendee country breakdown data."""

    country_code = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class AttendeeLevelBreakdownSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate attendee level breakdown data."""

    code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    tone = serializers.CharField()
    count = serializers.IntegerField()


class AttendeeReportSummarySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate attendee report summary data."""

    coming = serializers.IntegerField()
    confirmed = serializers.IntegerField()
    checked_in = serializers.IntegerField()
    countries = serializers.IntegerField()
    volunteers = serializers.IntegerField()
    approved_profile_photos = serializers.IntegerField()
    country_breakdown = AttendeeCountryBreakdownSerializer(many=True)
    level_breakdown = AttendeeLevelBreakdownSerializer(many=True)


class AttendeeReportRowSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate attendee report row data."""

    registration_id = serializers.UUIDField()
    reference = serializers.CharField()
    badge_name = serializers.CharField()
    badge_name_source = serializers.ChoiceField(
        choices=("registration_answer", "platform_display_name")
    )
    display_name = serializers.CharField()
    pronouns = serializers.CharField(allow_blank=True)
    spoken_language_codes = serializers.ListField(child=serializers.CharField())
    spoken_languages = serializers.ListField(child=serializers.CharField())
    country_code = serializers.CharField(allow_blank=True)
    registration_state = serializers.CharField()
    product_name = serializers.CharField()
    attendance_labels = AttendanceLabelSerializer(many=True)
    profile_photo_status = serializers.CharField()


class AttendeeReportSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate attendee report data."""

    generated_at = serializers.DateTimeField()
    status_scope = serializers.ListField(child=serializers.CharField())
    summary = AttendeeReportSummarySerializer()
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    has_next = serializers.BooleanField()
    has_previous = serializers.BooleanField()
    results = AttendeeReportRowSerializer(many=True)


class AttendeeReportQuerySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate attendee report query data."""

    search = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=100,
    )
    country_code = serializers.RegexField(
        r"^(?:[A-Za-z]{2}|unknown)$",
        required=False,
        max_length=7,
    )
    level = serializers.ChoiceField(
        required=False,
        choices=(
            "attendee",
            "sponsor",
            "super_sponsor",
            "volunteer",
            "guest",
        ),
    )
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        default=25,
    )


class StaffRegistrationListQuerySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate staff registration list query data."""

    search = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=100,
    )
    state = serializers.ChoiceField(
        required=False,
        choices=Registration.State.choices,
    )
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100)


class ActionItemSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate action item data."""

    key = serializers.CharField()
    level = serializers.ChoiceField(choices=("fyi", "action", "blocking", "urgent"))
    title = serializers.CharField()
    summary = serializers.CharField()
    object_type = serializers.CharField()
    object_id = serializers.UUIDField(allow_null=True)
    destination = serializers.CharField()
    owner_label = serializers.CharField()
    due_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
