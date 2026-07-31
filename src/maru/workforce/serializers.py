"""Stable client projections for volunteer opportunities and onboarding evidence."""

from rest_framework import serializers


class ConventionBootstrapOrganizationSerializer(
    serializers.Serializer[dict[str, object]]
):
    id = serializers.UUIDField()
    slug = serializers.SlugField()
    name = serializers.CharField()
    status = serializers.ChoiceField(choices=("eligible", "established"))


class ConventionBootstrapEditionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    organization_id = serializers.UUIDField()
    slug = serializers.SlugField()
    name = serializers.CharField()
    lifecycle = serializers.CharField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()


class ConventionBootstrapChairSerializer(serializers.Serializer[dict[str, object]]):
    email = serializers.EmailField()
    display_name = serializers.CharField()


class ConventionBootstrapWorkspaceSerializer(serializers.Serializer[dict[str, object]]):
    controller_email = serializers.EmailField()
    organizations = ConventionBootstrapOrganizationSerializer(many=True)
    editions = ConventionBootstrapEditionSerializer(many=True)
    chairs = ConventionBootstrapChairSerializer(many=True)


class ConventionBootstrapRequestSerializer(serializers.Serializer[dict[str, object]]):
    organization_id = serializers.UUIDField()
    edition_id = serializers.UUIDField()
    chair_email = serializers.EmailField()
    reason = serializers.CharField(
        max_length=500,
        allow_blank=False,
        trim_whitespace=True,
    )
    confirm_organization = serializers.SlugField(max_length=80)
    controller_password = serializers.CharField(
        max_length=256,
        allow_blank=False,
        trim_whitespace=False,
        write_only=True,
    )


class ConventionBootstrapCreatedSerializer(serializers.Serializer[dict[str, object]]):
    role_bundles = serializers.IntegerField()
    position_templates = serializers.IntegerField()
    departments = serializers.IntegerField()
    positions = serializers.IntegerField()
    role_assignments = serializers.IntegerField()
    position_assignments = serializers.IntegerField()


class ConventionBootstrapResultSerializer(serializers.Serializer[dict[str, object]]):
    organization = ConventionBootstrapOrganizationSerializer()
    edition = ConventionBootstrapEditionSerializer()
    chair = ConventionBootstrapChairSerializer()
    created = ConventionBootstrapCreatedSerializer()


class WorkforceStructureRoleSerializer(serializers.Serializer[dict[str, object]]):
    department_name = serializers.CharField()
    position_title = serializers.CharField()


class WorkforceStructureHolderSerializer(serializers.Serializer[dict[str, object]]):
    assignment_id = serializers.UUIDField()
    display_name = serializers.CharField()
    login_handle = serializers.CharField(allow_blank=True)
    other_roles = WorkforceStructureRoleSerializer(many=True)


class WorkforceStructurePositionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    reports_to_id = serializers.UUIDField(allow_null=True)
    code = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    headcount = serializers.IntegerField()
    status = serializers.CharField()
    holders = WorkforceStructureHolderSerializer(many=True)


class WorkforceStructureDepartmentSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    parent_id = serializers.UUIDField(allow_null=True)
    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    positions = WorkforceStructurePositionSerializer(many=True)


class WorkforceStructureSerializer(serializers.Serializer[dict[str, object]]):
    organization_name = serializers.CharField()
    edition_name = serializers.CharField()
    departments = WorkforceStructureDepartmentSerializer(many=True)


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
