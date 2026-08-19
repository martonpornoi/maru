"""Closed v1 API schemas for governed registration-definition commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from drf_spectacular.extensions import OpenApiSerializerExtension
from rest_framework import serializers

from maru.core.serializers import StrictInputSerializer
from maru.registration.models import (
    ProfileExtensionAudience,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    QuestionVisibility,
    RegistrationSetupOrigin,
)
from maru.registration.setup_commands import (
    MAX_PAYMENT_WINDOW_MINUTES,
    MAX_SETUP_CAPACITY,
    MAX_SETUP_MINIMUM_AGE,
    MAX_SETUP_NAME_LENGTH,
    MAX_SETUP_REASON_LENGTH,
    MIN_PAYMENT_WINDOW_MINUTES,
    RegistrationSetupStartResult,
)
from maru.registration.setup_definition_commands import (
    MAX_CONDITION_VALUE_LENGTH,
    MAX_DEFINITION_REASON_LENGTH,
    MAX_MINOR_JURISDICTION_LENGTH,
    MAX_MINOR_NOTICE_VERSION_LENGTH,
    MAX_MINOR_REVIEW_REFERENCE_LENGTH,
    MAX_PRODUCT_CAPACITY_CODES,
    MAX_PRODUCT_CODE_LENGTH,
    MAX_PRODUCT_DESCRIPTION_LENGTH,
    MAX_PRODUCT_ELIGIBILITY_LENGTH,
    MAX_PRODUCT_NAME_LENGTH,
    MAX_PRODUCT_PRICE_MINOR,
    MAX_QUESTION_HELP_LENGTH,
    MAX_QUESTION_LABEL_LENGTH,
    MAX_QUESTION_OPTION_LENGTH,
    MAX_QUESTION_OPTIONS,
    MAX_QUESTION_PURPOSE_LENGTH,
)
from maru.registration.setup_section_commands import (
    MAX_SECTION_DESCRIPTION_LENGTH,
    MAX_SECTION_KEY_LENGTH,
    MAX_SECTION_TITLE_LENGTH,
)

if TYPE_CHECKING:
    from datetime import datetime

    from drf_spectacular.openapi import AutoSchema
    from drf_spectacular.utils import Direction


class _RegistrationDefinitionClosedRequestSchema(OpenApiSerializerExtension):
    """Expose the strict command-object boundary in generated OpenAPI."""

    target_class = "maru.registration.setup_definition_serializers._CommandInput"
    match_subclasses = True

    def map_serializer(
        self,
        auto_schema: AutoSchema,
        direction: Direction,
    ) -> dict[str, Any]:
        schema = auto_schema._map_serializer(  # type: ignore[no-untyped-call]  # noqa: SLF001
            self.target,
            direction,
            bypass_extensions=True,
        )
        schema["additionalProperties"] = False
        return cast("dict[str, Any]", schema)


class _RegistrationSetupStartClosedRequestSchema(OpenApiSerializerExtension):
    target_class = (
        "maru.registration.setup_definition_serializers."
        "RegistrationSetupStartCommandSerializer"
    )

    def map_serializer(
        self,
        auto_schema: AutoSchema,
        direction: Direction,
    ) -> dict[str, Any]:
        schema = auto_schema._map_serializer(  # type: ignore[no-untyped-call]  # noqa: SLF001
            self.target,
            direction,
            bypass_extensions=True,
        )
        schema["additionalProperties"] = False
        return cast("dict[str, Any]", schema)


class RegistrationSetupStartCommandSerializer(StrictInputSerializer):
    """Serialize and validate registration setup start command data."""

    source_kind = serializers.ChoiceField(choices=RegistrationSetupOrigin.values)
    source_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    name = serializers.CharField(
        min_length=1,
        max_length=MAX_SETUP_NAME_LENGTH,
        trim_whitespace=True,
    )
    opens_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    closes_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    capacity = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        min_value=1,
        max_value=MAX_SETUP_CAPACITY,
    )
    capacity_ceiling = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        min_value=1,
        max_value=MAX_SETUP_CAPACITY,
    )
    currency = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        min_length=3,
        max_length=3,
    )
    minimum_age = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        min_value=0,
        max_value=MAX_SETUP_MINIMUM_AGE,
    )
    default_payment_window_minutes = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        min_value=MIN_PAYMENT_WINDOW_MINUTES,
        max_value=MAX_PAYMENT_WINDOW_MINUTES,
    )
    waitlist_enabled = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
    )
    automatic_waitlist_promotion = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
    )
    expected_version = serializers.IntegerField(min_value=0, max_value=0)
    reason = serializers.CharField(
        min_length=1,
        max_length=MAX_SETUP_REASON_LENGTH,
        trim_whitespace=True,
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
        attrs = super().validate(attrs)
        source_kind = attrs["source_kind"]
        source_id = attrs.get("source_id")
        if source_kind == RegistrationSetupOrigin.BLANK and source_id is not None:
            raise serializers.ValidationError(
                {"source_id": "Blank setup does not accept a source."}
            )
        if source_kind != RegistrationSetupOrigin.BLANK and source_id is None:
            raise serializers.ValidationError(
                {"source_id": "Choose one exact source version."}
            )
        if source_kind != RegistrationSetupOrigin.PRIOR_EDITION:
            required_metadata = (
                "opens_at",
                "closes_at",
                "capacity",
                "currency",
                "minimum_age",
                "default_payment_window_minutes",
                "waitlist_enabled",
                "automatic_waitlist_promotion",
            )
            missing = [name for name in required_metadata if attrs.get(name) is None]
            if missing:
                raise serializers.ValidationError(
                    dict.fromkeys(
                        missing,
                        (
                            "This value is required for blank, starter, and "
                            "template setup."
                        ),
                    )
                )
        opens_at = cast("datetime | None", attrs.get("opens_at"))
        closes_at = cast("datetime | None", attrs.get("closes_at"))
        if opens_at is not None and closes_at is not None and closes_at <= opens_at:
            raise serializers.ValidationError(
                {"closes_at": "Closing time must be after opening time."}
            )
        capacity = cast("int | None", attrs.get("capacity"))
        ceiling = cast("int | None", attrs.get("capacity_ceiling"))
        if capacity is not None and ceiling is not None and ceiling < capacity:
            raise serializers.ValidationError(
                {"capacity_ceiling": "The hard ceiling cannot be below capacity."}
            )
        if (
            attrs.get("waitlist_enabled") is False
            and attrs.get("automatic_waitlist_promotion") is True
        ):
            raise serializers.ValidationError(
                {
                    "automatic_waitlist_promotion": (
                        "Automatic promotion requires an enabled wait-list."
                    )
                }
            )
        currency = attrs.get("currency")
        if isinstance(currency, str):
            attrs["currency"] = currency.upper()
        return attrs


class RegistrationSetupSourceOptionSerializer(
    serializers.Serializer[dict[str, object]]
):
    source_kind = serializers.CharField()
    source_id = serializers.UUIDField()
    name = serializers.CharField()
    version = serializers.IntegerField(min_value=1)
    content_digest = serializers.CharField(min_length=64, max_length=64)
    source_edition_id = serializers.UUIDField(allow_null=True)
    source_edition_name = serializers.CharField(allow_blank=True)


class RegistrationSetupStartWorkspaceSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate registration setup start workspace data."""

    organization_id = serializers.UUIDField()
    series_id = serializers.UUIDField()
    edition_id = serializers.UUIDField()
    setup_state = serializers.CharField()
    aggregate_version = serializers.IntegerField(min_value=0)
    platform_starters = RegistrationSetupSourceOptionSerializer(many=True)
    published_templates = RegistrationSetupSourceOptionSerializer(many=True)
    prior_configurations = RegistrationSetupSourceOptionSerializer(many=True)


class RegistrationSetupStartResultSerializer(
    serializers.Serializer[RegistrationSetupStartResult]
):
    """Serialize and validate registration setup start result data."""

    setup_id = serializers.UUIDField()
    configuration_id = serializers.UUIDField()
    receipt_id = serializers.UUIDField()
    aggregate_version = serializers.IntegerField(min_value=1)
    configuration_version = serializers.IntegerField(min_value=1)
    source_kind = serializers.CharField()
    content_digest = serializers.CharField(min_length=64, max_length=64)
    section_count = serializers.IntegerField(min_value=0)
    question_count = serializers.IntegerField(min_value=0)
    product_count = serializers.IntegerField(min_value=0)
    minor_policy_copied = serializers.BooleanField()
    replayed = serializers.BooleanField()


class _CommandInput(StrictInputSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(
        min_length=1,
        max_length=MAX_DEFINITION_REASON_LENGTH,
        trim_whitespace=True,
    )


class _SectionInput(_CommandInput):
    key = serializers.SlugField(
        min_length=1,
        max_length=MAX_SECTION_KEY_LENGTH,
    )
    title = serializers.CharField(
        min_length=1,
        max_length=MAX_SECTION_TITLE_LENGTH,
        trim_whitespace=True,
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_SECTION_DESCRIPTION_LENGTH,
    )


class RegistrationSectionCreateCommandSerializer(_SectionInput):
    operation = serializers.ChoiceField(choices=("section.create",))
    after_section_id = serializers.UUIDField(required=False, allow_null=True)


class RegistrationSectionUpdateCommandSerializer(_SectionInput):
    operation = serializers.ChoiceField(choices=("section.update",))
    section_id = serializers.UUIDField()


class RegistrationSectionMoveCommandSerializer(_CommandInput):
    operation = serializers.ChoiceField(choices=("section.move",))
    section_id = serializers.UUIDField()
    after_section_id = serializers.UUIDField(required=False, allow_null=True)


class RegistrationSectionRemoveCommandSerializer(_CommandInput):
    operation = serializers.ChoiceField(choices=("section.remove",))
    section_id = serializers.UUIDField()


class _QuestionInput(_CommandInput):
    key = serializers.SlugField(min_length=1, max_length=MAX_SECTION_KEY_LENGTH)
    label = serializers.CharField(  # type: ignore[assignment]
        min_length=1,
        max_length=MAX_QUESTION_LABEL_LENGTH,
        trim_whitespace=True,
    )
    help_text = serializers.CharField(  # type: ignore[assignment]
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_QUESTION_HELP_LENGTH,
    )
    field_type = serializers.ChoiceField(choices=QuestionFieldType.values)
    required = serializers.BooleanField()  # type: ignore[assignment]
    options = serializers.ListField(
        child=serializers.CharField(
            min_length=1,
            max_length=MAX_QUESTION_OPTION_LENGTH,
            trim_whitespace=True,
        ),
        required=False,
        default=list,
        max_length=MAX_QUESTION_OPTIONS,
    )
    purpose = serializers.CharField(
        min_length=1,
        max_length=MAX_QUESTION_PURPOSE_LENGTH,
        trim_whitespace=True,
    )
    visibility = serializers.ChoiceField(choices=QuestionVisibility.values)
    classification = serializers.ChoiceField(choices=QuestionClassification.values)
    condition_question_key = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_SECTION_KEY_LENGTH,
    )
    condition_value = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_CONDITION_VALUE_LENGTH,
    )
    section_id = serializers.UUIDField(required=False, allow_null=True)


class RegistrationQuestionCreateCommandSerializer(_QuestionInput):
    operation = serializers.ChoiceField(choices=("question.create",))
    after_question_id = serializers.UUIDField(required=False, allow_null=True)


class RegistrationQuestionUpdateCommandSerializer(_QuestionInput):
    operation = serializers.ChoiceField(choices=("question.update",))
    question_id = serializers.UUIDField()


class RegistrationQuestionMoveCommandSerializer(_CommandInput):
    operation = serializers.ChoiceField(choices=("question.move",))
    question_id = serializers.UUIDField()
    after_question_id = serializers.UUIDField(required=False, allow_null=True)


class RegistrationQuestionRemoveCommandSerializer(_CommandInput):
    operation = serializers.ChoiceField(choices=("question.remove",))
    question_id = serializers.UUIDField()


class _ProductInput(_CommandInput):
    code = serializers.SlugField(min_length=1, max_length=MAX_PRODUCT_CODE_LENGTH)
    name = serializers.CharField(
        min_length=1,
        max_length=MAX_PRODUCT_NAME_LENGTH,
        trim_whitespace=True,
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_PRODUCT_DESCRIPTION_LENGTH,
    )
    price_minor = serializers.IntegerField(
        min_value=0,
        max_value=MAX_PRODUCT_PRICE_MINOR,
    )
    capacity = serializers.IntegerField(min_value=1, max_value=MAX_SETUP_CAPACITY)
    capacity_ceiling = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=MAX_SETUP_CAPACITY,
    )
    entitlement_code = serializers.SlugField(
        min_length=1,
        max_length=MAX_PRODUCT_CODE_LENGTH,
    )
    entitlement_name = serializers.CharField(
        min_length=1,
        max_length=MAX_PRODUCT_NAME_LENGTH,
        trim_whitespace=True,
    )
    sales_open_at = serializers.DateTimeField(required=False, allow_null=True)
    sales_close_at = serializers.DateTimeField(required=False, allow_null=True)
    required_capacity_codes = serializers.ListField(
        child=serializers.SlugField(
            min_length=1,
            max_length=MAX_PRODUCT_CODE_LENGTH,
        ),
        required=False,
        default=list,
        max_length=MAX_PRODUCT_CAPACITY_CODES,
    )
    eligibility_explanation = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_PRODUCT_ELIGIBILITY_LENGTH,
    )
    waitlist_enabled = serializers.BooleanField()
    payment_window_minutes = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=MIN_PAYMENT_WINDOW_MINUTES,
        max_value=MAX_PAYMENT_WINDOW_MINUTES,
    )


class RegistrationProductCreateCommandSerializer(_ProductInput):
    operation = serializers.ChoiceField(choices=("product.create",))
    after_product_id = serializers.UUIDField(required=False, allow_null=True)


class RegistrationProductUpdateCommandSerializer(_ProductInput):
    operation = serializers.ChoiceField(choices=("product.update",))
    product_id = serializers.UUIDField()


class RegistrationProductMoveCommandSerializer(_CommandInput):
    operation = serializers.ChoiceField(choices=("product.move",))
    product_id = serializers.UUIDField()
    after_product_id = serializers.UUIDField(required=False, allow_null=True)


class RegistrationProductRemoveCommandSerializer(_CommandInput):
    operation = serializers.ChoiceField(choices=("product.remove",))
    product_id = serializers.UUIDField()


class RegistrationMinorPolicySetCommandSerializer(_CommandInput):
    operation = serializers.ChoiceField(choices=("minor_policy.set",))
    enabled = serializers.BooleanField()
    minor_age_threshold = serializers.IntegerField(min_value=1, max_value=120)
    guardian_notice_version = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_MINOR_NOTICE_VERSION_LENGTH,
    )
    jurisdiction_code = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_MINOR_JURISDICTION_LENGTH,
    )
    review_reference = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_MINOR_REVIEW_REFERENCE_LENGTH,
    )


class RegistrationMinorPolicyRemoveCommandSerializer(_CommandInput):
    operation = serializers.ChoiceField(choices=("minor_policy.remove",))


class _ProfileFieldInput(_CommandInput):
    key = serializers.SlugField(min_length=1, max_length=MAX_SECTION_KEY_LENGTH)
    label = serializers.CharField(  # type: ignore[assignment]
        min_length=1,
        max_length=MAX_QUESTION_LABEL_LENGTH,
        trim_whitespace=True,
    )
    help_text = serializers.CharField(  # type: ignore[assignment]
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_QUESTION_HELP_LENGTH,
    )
    field_type = serializers.ChoiceField(choices=QuestionFieldType.values)
    options = serializers.ListField(
        child=serializers.CharField(
            min_length=1,
            max_length=MAX_QUESTION_OPTION_LENGTH,
            trim_whitespace=True,
        ),
        required=False,
        default=list,
        max_length=MAX_QUESTION_OPTIONS,
    )
    purpose = serializers.CharField(
        min_length=1,
        max_length=MAX_QUESTION_PURPOSE_LENGTH,
        trim_whitespace=True,
    )
    classification = serializers.ChoiceField(choices=QuestionClassification.values)
    audience_policy = serializers.ChoiceField(
        choices=ProfileExtensionAudience.values,
        required=False,
    )
    audience_department_id = serializers.UUIDField(required=False, allow_null=True)
    attendee_visible = serializers.BooleanField(required=False, write_only=True)
    writer_policy = serializers.ChoiceField(choices=ProfileExtensionWriter.values)
    required = serializers.BooleanField()  # type: ignore[assignment]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        attrs = super().validate(attrs)
        audience_policy = attrs.get("audience_policy")
        legacy_visibility = attrs.pop("attendee_visible", None)
        if audience_policy is None and legacy_visibility is not None:
            attrs["audience_policy"] = (
                ProfileExtensionAudience.SELF
                if legacy_visibility is True
                else ProfileExtensionAudience.REGISTRATION_STAFF
            )
        elif audience_policy is None:
            raise serializers.ValidationError(
                {"audience_policy": "This field is required."}
            )
        elif legacy_visibility is not None:
            raise serializers.ValidationError(
                {
                    "attendee_visible": (
                        "Use audience_policy instead of the legacy visibility input."
                    )
                }
            )
        return attrs


class RegistrationProfileFieldCreateSerializer(_ProfileFieldInput):
    """Serialize and validate registration profile field create data."""

    source_template_id = serializers.UUIDField(required=False, allow_null=True)
    source_prior_edition_id = serializers.UUIDField(required=False, allow_null=True)
    after_field_id = serializers.UUIDField(required=False, allow_null=True)


class RegistrationProfileFieldUpdateCommandSerializer(_ProfileFieldInput):
    operation = serializers.ChoiceField(choices=("profile_field.update",))


class RegistrationProfileFieldMoveCommandSerializer(_CommandInput):
    operation = serializers.ChoiceField(choices=("profile_field.move",))
    after_field_id = serializers.UUIDField(required=False, allow_null=True)


class RegistrationProfileFieldRetireCommandSerializer(_CommandInput):
    operation = serializers.ChoiceField(choices=("profile_field.retire",))


class RegistrationDefinitionMutationSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate registration definition mutation data."""

    setup_id = serializers.UUIDField()
    receipt_id = serializers.UUIDField()
    target_id = serializers.UUIDField()
    resulting_version = serializers.IntegerField(min_value=1)
    action = serializers.CharField()
    configuration_id = serializers.UUIDField(allow_null=True)
    configuration_content_digest = serializers.CharField()
    replayed = serializers.BooleanField()


class RegistrationProfileExtensionFieldSerializer(
    serializers.Serializer[dict[str, object]]
):
    id = serializers.UUIDField()
    key = serializers.CharField()
    version = serializers.IntegerField(min_value=1)
    label = serializers.CharField()  # type: ignore[assignment]
    help_text = serializers.CharField()  # type: ignore[assignment]
    field_type = serializers.CharField()
    options = serializers.ListField(child=serializers.CharField())
    purpose = serializers.CharField()
    classification = serializers.CharField()
    audience_policy = serializers.CharField()
    audience_department_id = serializers.UUIDField(allow_null=True)
    audience_department_name = serializers.CharField(allow_blank=True)
    writer_policy = serializers.CharField()
    required = serializers.BooleanField()  # type: ignore[assignment]
    position = serializers.IntegerField(min_value=0)
    source_template_id = serializers.UUIDField(allow_null=True)
    source_prior_edition_id = serializers.UUIDField(allow_null=True)
    review_status = serializers.CharField()
    status = serializers.CharField()


class RegistrationProfileExtensionCatalogSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate registration profile extension catalog data."""

    organization_id = serializers.UUIDField()
    edition_id = serializers.UUIDField()
    aggregate_version = serializers.IntegerField(min_value=0)
    fields = RegistrationProfileExtensionFieldSerializer(  # type: ignore[assignment]
        many=True
    )


class RegistrationSetupProblemSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate registration setup problem data."""

    type = serializers.URLField()
    title = serializers.CharField()
    status = serializers.IntegerField()
    detail = serializers.CharField()
    code = serializers.CharField()
    request_id = serializers.UUIDField(required=False)
    errors = serializers.JSONField(required=False)  # type: ignore[assignment]


CONFIGURATION_COMMAND_SERIALIZERS = (
    RegistrationSectionCreateCommandSerializer,
    RegistrationSectionUpdateCommandSerializer,
    RegistrationSectionMoveCommandSerializer,
    RegistrationSectionRemoveCommandSerializer,
    RegistrationQuestionCreateCommandSerializer,
    RegistrationQuestionUpdateCommandSerializer,
    RegistrationQuestionMoveCommandSerializer,
    RegistrationQuestionRemoveCommandSerializer,
    RegistrationProductCreateCommandSerializer,
    RegistrationProductUpdateCommandSerializer,
    RegistrationProductMoveCommandSerializer,
    RegistrationProductRemoveCommandSerializer,
    RegistrationMinorPolicySetCommandSerializer,
    RegistrationMinorPolicyRemoveCommandSerializer,
)

PROFILE_FIELD_COMMAND_SERIALIZERS = (
    RegistrationProfileFieldUpdateCommandSerializer,
    RegistrationProfileFieldMoveCommandSerializer,
    RegistrationProfileFieldRetireCommandSerializer,
)


def _single_operation(
    serializer_class: type[StrictInputSerializer],
) -> str:
    operation_field = cast(
        "serializers.ChoiceField",
        serializer_class().fields["operation"],
    )
    return str(next(iter(operation_field.choices)))


COMMAND_SERIALIZER_BY_OPERATION = {
    _single_operation(serializer): serializer
    for serializer in CONFIGURATION_COMMAND_SERIALIZERS
}

PROFILE_COMMAND_SERIALIZER_BY_OPERATION = {
    _single_operation(serializer): serializer
    for serializer in PROFILE_FIELD_COMMAND_SERIALIZERS
}


__all__ = [
    "COMMAND_SERIALIZER_BY_OPERATION",
    "CONFIGURATION_COMMAND_SERIALIZERS",
    "PROFILE_COMMAND_SERIALIZER_BY_OPERATION",
    "PROFILE_FIELD_COMMAND_SERIALIZERS",
    "RegistrationDefinitionMutationSerializer",
    "RegistrationProfileExtensionCatalogSerializer",
    "RegistrationProfileFieldCreateSerializer",
    "RegistrationSetupProblemSerializer",
    "RegistrationSetupStartCommandSerializer",
    "RegistrationSetupStartResultSerializer",
    "RegistrationSetupStartWorkspaceSerializer",
]
