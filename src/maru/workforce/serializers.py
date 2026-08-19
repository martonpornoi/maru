"""Stable workforce request and response contracts."""

from typing import TYPE_CHECKING, Any, ClassVar, Never, cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.extensions import OpenApiSerializerExtension
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from maru.workforce.models import Position
from maru.workforce.structure_inputs import (
    CANONICAL_UUID_PATTERN,
    MAX_DEPARTMENT_DESCRIPTION_LENGTH,
    MAX_DEPARTMENT_NAME_LENGTH,
    MAX_STRUCTURE_REASON_LENGTH,
    normalize_department_description,
    normalize_department_name,
    normalize_structure_reason,
)
from maru.workforce.structure_templates import AWOOSTRIA_REFERENCE_V1

if TYPE_CHECKING:
    from drf_spectacular.openapi import AutoSchema
    from drf_spectacular.utils import Direction


def _django_validation_code(
    error: DjangoValidationError,
    *,
    fallback: str,
) -> str:
    if hasattr(error, "error_dict"):
        for field_errors in error.error_dict.values():
            if field_errors:
                return str(field_errors[0].code or fallback)
    if hasattr(error, "error_list") and error.error_list:
        return str(error.error_list[0].code or fallback)
    return fallback


def _raise_serializer_validation(
    error: DjangoValidationError,
    *,
    fallback: str,
) -> Never:
    raise serializers.ValidationError(
        error.messages,
        code=_django_validation_code(error, fallback=fallback),
    ) from error


class _StrictStructureTextField(serializers.CharField):
    """A JSON string field which never coerces numbers or booleans."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid_type": "Enter a JSON string for this field.",
    }

    def to_internal_value(self, data: object) -> str:
        if not isinstance(data, str):
            self.fail("invalid_type")
        return super().to_internal_value(data)


class _NormalizedDepartmentNameField(_StrictStructureTextField):
    def to_internal_value(self, data: object) -> str:
        raw = super().to_internal_value(data)
        try:
            return normalize_department_name(raw)
        except DjangoValidationError as error:
            _raise_serializer_validation(error, fallback="structure_name_invalid")


class _NormalizedDepartmentDescriptionField(_StrictStructureTextField):
    def to_internal_value(self, data: object) -> str:
        raw = super().to_internal_value(data)
        try:
            return normalize_department_description(raw)
        except DjangoValidationError as error:
            _raise_serializer_validation(
                error,
                fallback="structure_description_invalid",
            )


class _NormalizedStructureReasonField(_StrictStructureTextField):
    def to_internal_value(self, data: object) -> str:
        raw = super().to_internal_value(data)
        try:
            return normalize_structure_reason(raw)
        except DjangoValidationError as error:
            _raise_serializer_validation(error, fallback="structure_reason_invalid")


class _StrictStructureIntegerField(serializers.IntegerField):
    """Accept a JSON integer, excluding bool, string and float coercion."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid_type": "Enter a JSON integer for this field.",
    }

    def to_internal_value(self, data: object) -> int:
        if type(data) is not int:
            self.fail("invalid_type")
        return super().to_internal_value(data)


@extend_schema_field(
    {
        "type": "string",
        "format": "uuid",
        "pattern": CANONICAL_UUID_PATTERN,
    }
)
class _CanonicalStructureUUIDField(serializers.UUIDField):
    """Accept only the lower-case hyphenated UUID spelling used by Maru."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "non_canonical": "Enter a canonical lower-case hyphenated UUID.",
    }

    def to_internal_value(self, data: object) -> UUID:
        if not isinstance(data, str):
            self.fail("invalid")
        try:
            value = UUID(data)
        except (AttributeError, ValueError):
            self.fail("invalid")
        if str(value) != data:
            self.fail("non_canonical")
        return value


class _StrictStructureChoiceField(serializers.ChoiceField):
    def to_internal_value(self, data: object) -> str:
        if not isinstance(data, str):
            self.fail("invalid_choice", input=data)
        return super().to_internal_value(data)


class WorkforceProblemSerializer(serializers.Serializer[dict[str, object]]):
    """RFC 9457 response shape used by workforce endpoints."""

    type = serializers.URLField(read_only=True)
    title = serializers.CharField(read_only=True)
    status = serializers.IntegerField(read_only=True)
    detail = serializers.CharField(read_only=True)
    code = serializers.CharField(read_only=True)
    request_id = serializers.UUIDField(required=False)
    errors = serializers.JSONField(required=False)  # type: ignore[assignment]


class WorkforceStructureRoleSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate workforce structure role data."""

    department_name = serializers.CharField()
    position_title = serializers.CharField()


class WorkforceStructureHolderSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate workforce structure holder data."""

    display_name = serializers.CharField()
    other_roles = WorkforceStructureRoleSerializer(many=True)


class WorkforceStructurePositionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate workforce structure position data."""

    id = serializers.UUIDField()
    reports_to_id = serializers.UUIDField(allow_null=True)
    reports_to_title = serializers.CharField(allow_null=True)
    code = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    headcount = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Position.Status.choices)
    holders = WorkforceStructureHolderSerializer(many=True)


class WorkforceStructureDepartmentSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate workforce structure department data."""

    id = serializers.UUIDField()
    parent_id = serializers.UUIDField(allow_null=True)
    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    display_order = serializers.IntegerField()
    state = serializers.ChoiceField(choices=("active", "retired"))
    positions = WorkforceStructurePositionSerializer(many=True)
    children = serializers.SerializerMethodField()

    @extend_schema_field(
        {
            "type": "array",
            "items": {
                "$ref": "#/components/schemas/WorkforceStructureDepartment",
            },
        }
    )
    def get_children(self, item: dict[str, object]) -> list[dict[str, object]]:
        """Return children.

        Parameters
        ----------
        item : dict[str, object]
            The domain object being validated, rendered, or persisted.

        Returns
        -------
        list[dict[str, object]]
            The matching get children records in deterministic order.
        """
        children = item.get("children", ())
        return cast(
            "list[dict[str, object]]",
            WorkforceStructureDepartmentSerializer(
                children,  # type: ignore[arg-type]
                many=True,
            ).data,
        )


class WorkforceStructureGovernanceSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate workforce structure governance data."""

    kind = serializers.ChoiceField(choices=("governance",))
    label = serializers.CharField()  # type: ignore[assignment]
    state = serializers.ChoiceField(
        choices=("absent", "provisioning", "active", "suspended")
    )


class WorkforceStructureEmptySourceSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate workforce structure empty source data."""

    kind = serializers.ChoiceField(choices=("empty",))


class WorkforceStructureManualSourceSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate workforce structure manual source data."""

    kind = serializers.ChoiceField(choices=("manual",))


class WorkforceStructureLegacySourceSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate workforce structure legacy source data."""

    kind = serializers.ChoiceField(choices=("legacy_existing",))


class WorkforceStructureBuiltinTemplateSourceSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate workforce structure builtin template source data."""

    kind = serializers.ChoiceField(choices=("builtin_template",))
    template_code = serializers.CharField()
    template_version = serializers.IntegerField(min_value=1)


_WORKFORCE_STRUCTURE_SOURCE_SERIALIZERS = {
    "empty": WorkforceStructureEmptySourceSerializer,
    "manual": WorkforceStructureManualSourceSerializer,
    "legacy_existing": WorkforceStructureLegacySourceSerializer,
    "builtin_template": WorkforceStructureBuiltinTemplateSourceSerializer,
}


@extend_schema_field(
    PolymorphicProxySerializer(
        component_name="WorkforceStructureSource",
        serializers=cast(
            "dict[str, serializers.Serializer[Any] | "
            "type[serializers.Serializer[Any]]]",
            _WORKFORCE_STRUCTURE_SOURCE_SERIALIZERS,
        ),
        resource_type_field_name="kind",
    )
)
class WorkforceStructureSourceField(
    serializers.Field[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        dict[str, object],
    ]
):
    """Render only the fields allowed by the source discriminator."""

    def to_representation(self, value: dict[str, object]) -> dict[str, object]:
        """Serialize the instance for API output.

        Parameters
        ----------
        value : dict[str, object]
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        dict[str, object]
            A mapping containing the resolved to representation data.
        """
        serializer_class = _WORKFORCE_STRUCTURE_SOURCE_SERIALIZERS.get(
            str(value.get("kind"))
        )
        if serializer_class is None:
            return {}
        return cast("dict[str, object]", serializer_class(value).data)


class WorkforceStructureProjectionSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate workforce structure projection data."""

    state = serializers.ChoiceField(choices=("complete", "structure_limit_exceeded"))
    aggregate_version = serializers.IntegerField(min_value=0)
    source = WorkforceStructureSourceField()  # type: ignore[assignment]
    departments = WorkforceStructureDepartmentSerializer(many=True)


class WorkforceStructureSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate workforce structure data."""

    organization_name = serializers.CharField()
    series_name = serializers.CharField()
    edition_name = serializers.CharField()
    governance = WorkforceStructureGovernanceSerializer()
    structure = WorkforceStructureProjectionSerializer()


class _ClosedStructureRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Marker base for Page 9 request objects that reject unknown properties."""


class _ClosedStructureRequestSchema(OpenApiSerializerExtension):
    """Expose the runtime closed-object contract in generated OpenAPI."""

    target_class = "maru.workforce.serializers._ClosedStructureRequestSerializer"
    match_subclasses = True

    def map_serializer(
        self,
        auto_schema: "AutoSchema",
        direction: "Direction",
    ) -> dict[str, Any]:
        schema = auto_schema._map_serializer(  # type: ignore[no-untyped-call]
            self.target,
            direction,
            bypass_extensions=True,
        )
        schema["additionalProperties"] = False
        return cast("dict[str, Any]", schema)


class WorkforceStructureTemplateApplySerializer(_ClosedStructureRequestSerializer):
    """Closed API input for one immutable built-in template application."""

    template = _StrictStructureChoiceField(
        choices=(AWOOSTRIA_REFERENCE_V1.identifier,),
    )
    expected_version = _StrictStructureIntegerField(min_value=0, max_value=0)
    confirmation_name = _StrictStructureTextField(
        max_length=160,
        trim_whitespace=False,
    )
    reason = _NormalizedStructureReasonField(
        max_length=MAX_STRUCTURE_REASON_LENGTH,
        trim_whitespace=False,
    )


class WorkforceDepartmentCreateSerializer(_ClosedStructureRequestSerializer):
    """Closed API input for one idempotent Department creation."""

    name = _NormalizedDepartmentNameField(
        max_length=MAX_DEPARTMENT_NAME_LENGTH,
        trim_whitespace=False,
    )
    description = _NormalizedDepartmentDescriptionField(
        max_length=MAX_DEPARTMENT_DESCRIPTION_LENGTH,
        trim_whitespace=False,
        allow_blank=True,
    )
    parent_department_id = _CanonicalStructureUUIDField(allow_null=True)
    display_order = _StrictStructureIntegerField(min_value=0, max_value=65_535)
    expected_version = _StrictStructureIntegerField(min_value=0)
    reason = _NormalizedStructureReasonField(
        max_length=MAX_STRUCTURE_REASON_LENGTH,
        trim_whitespace=False,
    )


class WorkforceDepartmentUpdateSerializer(WorkforceDepartmentCreateSerializer):
    """Complete replacement input; creation retry metadata is header-only."""

    expected_version = _StrictStructureIntegerField(min_value=1)


class WorkforceDepartmentRetireSerializer(_ClosedStructureRequestSerializer):
    """Closed API input for one dependency-safe Department retirement."""

    expected_version = _StrictStructureIntegerField(min_value=1)
    reason = _NormalizedStructureReasonField(
        max_length=MAX_STRUCTURE_REASON_LENGTH,
        trim_whitespace=False,
    )


class WorkforceDepartmentDeleteSerializer(WorkforceDepartmentRetireSerializer):
    """Closed API input for one protected Department deletion."""

    confirmation_name = _StrictStructureTextField(
        max_length=MAX_DEPARTMENT_NAME_LENGTH,
        trim_whitespace=False,
    )


class WorkforceStructureTemplateMutationResultSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate workforce structure template mutation result data."""

    aggregate_version = serializers.IntegerField(min_value=1)


class WorkforceDepartmentMutationResultSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Serialize and validate workforce department mutation result data."""

    department_id = serializers.UUIDField()
    aggregate_version = serializers.IntegerField(min_value=1)


class VolunteerOpportunitySerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate volunteer opportunity data."""

    id = serializers.UUIDField()
    position_code = serializers.CharField()
    position_title = serializers.CharField()
    department_name = serializers.CharField()
    reports_to_title = serializers.CharField(allow_null=True)
    headline = serializers.CharField()
    description = serializers.CharField()
    headcount = serializers.IntegerField()
    active_assignment_count = serializers.IntegerField()
    is_filled = serializers.BooleanField()
    accepts_applications = serializers.BooleanField()
    applications_open_at = serializers.DateTimeField(allow_null=True)
    applications_close_at = serializers.DateTimeField(allow_null=True)


class VolunteerApplicationSubmitSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate volunteer application submit data."""

    motivation = serializers.CharField(max_length=2_000)


class VolunteerApplicationSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate volunteer application data."""

    id = serializers.UUIDField()
    opportunity_id = serializers.UUIDField()
    status = serializers.CharField()
    submitted_at = serializers.DateTimeField()


class OnboardingDocumentRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate onboarding document request data."""

    id = serializers.UUIDField()
    document_type_code = serializers.CharField()
    document_type_name = serializers.CharField()
    document_type_version = serializers.IntegerField()
    status = serializers.CharField()
    instructions = serializers.CharField()
    due_at = serializers.DateTimeField(allow_null=True)
    requested_at = serializers.DateTimeField()
    submitted_at = serializers.DateTimeField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)
    review_reason = serializers.CharField()
    original_filename = serializers.CharField()
    upload_available = serializers.BooleanField()


class OnboardingDocumentUploadSerializer(serializers.Serializer[dict[str, object]]):
    """Serialize and validate onboarding document upload data."""

    document = serializers.FileField()
