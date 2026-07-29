"""Stable client projections for volunteer opportunities and onboarding evidence."""

from rest_framework import serializers


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
