"""Stable client projections for volunteer opportunities and onboarding evidence."""

from typing import cast

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from maru.workforce.models import Position


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
    department_name = serializers.CharField()
    position_title = serializers.CharField()


class WorkforceStructureHolderSerializer(serializers.Serializer[dict[str, object]]):
    display_name = serializers.CharField()
    other_roles = WorkforceStructureRoleSerializer(many=True)


class WorkforceStructurePositionSerializer(serializers.Serializer[dict[str, object]]):
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
    id = serializers.UUIDField()
    parent_id = serializers.UUIDField(allow_null=True)
    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    display_order = serializers.IntegerField()
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
        children = item.get("children", ())
        return cast(
            list[dict[str, object]],
            WorkforceStructureDepartmentSerializer(
                children,  # type: ignore[arg-type]
                many=True,
            ).data,
        )


class WorkforceStructureGovernanceSerializer(serializers.Serializer[dict[str, object]]):
    kind = serializers.ChoiceField(choices=("governance",))
    label = serializers.CharField()  # type: ignore[assignment]
    state = serializers.ChoiceField(
        choices=("absent", "provisioning", "active", "suspended")
    )


class WorkforceStructureProjectionSerializer(serializers.Serializer[dict[str, object]]):
    state = serializers.ChoiceField(choices=("complete", "structure_limit_exceeded"))
    departments = WorkforceStructureDepartmentSerializer(many=True)


class WorkforceStructureSerializer(serializers.Serializer[dict[str, object]]):
    organization_name = serializers.CharField()
    edition_name = serializers.CharField()
    governance = WorkforceStructureGovernanceSerializer()
    structure = WorkforceStructureProjectionSerializer()


class VolunteerOpportunitySerializer(serializers.Serializer[dict[str, object]]):
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
    motivation = serializers.CharField(max_length=2_000)


class VolunteerApplicationSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    opportunity_id = serializers.UUIDField()
    status = serializers.CharField()
    submitted_at = serializers.DateTimeField()


class OnboardingDocumentRequestSerializer(serializers.Serializer[dict[str, object]]):
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
    document = serializers.FileField()
