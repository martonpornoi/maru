"""Authorized edition API projections."""

from uuid import UUID

from rest_framework import serializers

from maru.events.models import (
    EditionClosureManifest,
    EditionReadinessGate,
    EventEdition,
)

MAX_AUTOCOMPLETE_RESULTS = 20
MAX_BULK_EDITION_TRANSITIONS = 25


class EditionBasicSerializer(serializers.ModelSerializer[EventEdition]):
    class Meta:
        model = EventEdition
        fields = (
            "id",
            "organization_id",
            "series_id",
            "slug",
            "name",
            "lifecycle",
            "time_zone",
            "language_codes",
            "currency_codes",
            "starts_on",
            "ends_on",
        )
        read_only_fields = fields


class EditionListQuerySerializer(serializers.Serializer[dict[str, str]]):
    lifecycle = serializers.ChoiceField(
        choices=EventEdition.Lifecycle.choices,
        required=False,
    )
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=100,
    )
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
    )


class EditionAutocompleteSerializer(serializers.ModelSerializer[EventEdition]):
    class Meta:
        model = EventEdition
        fields = ("id", "name", "lifecycle", "starts_on")
        read_only_fields = fields


class EditionAutocompleteQuerySerializer(serializers.Serializer[dict[str, object]]):
    search = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        min_length=1,
        max_length=100,
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_AUTOCOMPLETE_RESULTS,
        default=10,
    )


class EditionAutocompleteResponseSerializer(serializers.Serializer[dict[str, object]]):
    results = EditionAutocompleteSerializer(many=True, read_only=True)


class EditionTransitionRequestSerializer(serializers.Serializer[dict[str, str]]):
    to_state = serializers.ChoiceField(choices=EventEdition.Lifecycle.choices)
    reason = serializers.CharField(
        max_length=500,
        allow_blank=False,
        trim_whitespace=True,
    )


class EditionTransitionResultSerializer(serializers.ModelSerializer[EventEdition]):
    class Meta:
        model = EventEdition
        fields = ("id", "lifecycle", "lifecycle_version")
        read_only_fields = fields


class EditionBulkTransitionRequestSerializer(serializers.Serializer[dict[str, object]]):
    edition_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_BULK_EDITION_TRANSITIONS,
    )
    to_state = serializers.ChoiceField(choices=EventEdition.Lifecycle.choices)
    reason = serializers.CharField(
        max_length=500,
        allow_blank=False,
        trim_whitespace=True,
    )

    def validate_edition_ids(self, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise serializers.ValidationError(
                "Edition identifiers must be unique.",
                code="duplicate_target",
            )
        return value


class EditionBulkTransitionResponseSerializer(
    serializers.Serializer[dict[str, object]]
):
    results = EditionTransitionResultSerializer(many=True, read_only=True)


class EditionReadinessGateSerializer(serializers.ModelSerializer[EditionReadinessGate]):
    class Meta:
        model = EditionReadinessGate
        fields = (
            "id",
            "code",
            "status",
            "evidence_reference",
            "review_summary",
            "reviewed_at",
        )
        read_only_fields = fields


class EditionReadinessGateReviewSerializer(serializers.Serializer[dict[str, object]]):
    approve = serializers.BooleanField()
    evidence_reference = serializers.CharField(max_length=240)
    summary = serializers.CharField(max_length=500)


class EditionClosureManifestCreateSerializer(serializers.Serializer[dict[str, str]]):
    recovery_reference = serializers.CharField(max_length=240)


class EditionClosureManifestSerializer(
    serializers.ModelSerializer[EditionClosureManifest]
):
    class Meta:
        model = EditionClosureManifest
        fields = (
            "id",
            "generated_at",
            "counts",
            "manifest_digest",
            "recovery_reference",
        )
        read_only_fields = fields
